"""Select configuration records and prepare literal workbook values in memory."""

import json
import math
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from .schema import RESOURCE_SHEETS, CellKind, ColumnSpec, get_sheet_spec
from .source import SOURCE_COLUMNS

_Rows = dict[str, dict[int, dict[str, object]]]
_MAX_ID = 2**63 - 1


class WorkbookExportError(ValueError):
    """A source record or export selection cannot satisfy the workbook contract."""

    def __init__(
        self, sheet: str, database_id: int | None, column: str, message: str,
    ) -> None:
        self.sheet = sheet
        self.database_id = database_id
        self.column = column
        location = sheet if database_id is None else f"{sheet}[id={database_id}]"
        super().__init__(f"{location}.{column}: {message}")


@dataclass(frozen=True)
class WorkbookExport:
    """Export metadata and caller-owned frames in workbook column order.

    The frames remain mutable. They contain fresh scalar workbook values and
    share no mutable JSON objects with the input frames.
    """

    scope: str
    site_ids: tuple[int, ...]
    frames: dict[str, pd.DataFrame]


def _valid_id(value: object) -> bool:
    return type(value) is int and 0 < value <= _MAX_ID


def _index_frames(frames: Mapping[str, pd.DataFrame]) -> _Rows:
    if set(frames) != set(SOURCE_COLUMNS):
        raise WorkbookExportError(
            "source", None, "sheets", "expected exactly the eleven configuration frames",
        )
    indexed: _Rows = {}
    for name, columns in SOURCE_COLUMNS.items():
        frame = frames[name]
        if (
            not isinstance(frame, pd.DataFrame)
            or not frame.columns.is_unique
            or set(frame.columns) != set(columns)
        ):
            raise WorkbookExportError(name, None, "columns", "invalid source columns")
        records = {}
        for values in frame.loc[:, list(columns)].itertuples(index=False, name=None):
            row = dict(zip(columns, values))
            database_id = row[columns[0]]
            if not _valid_id(database_id):
                raise WorkbookExportError(name, None, columns[0], "expected a positive BIGINT ID")
            if database_id in records:
                raise WorkbookExportError(name, database_id, columns[0], "duplicate ID")
            records[database_id] = row
        indexed[name] = records
    return indexed


def _select_rows(
    rows: _Rows, requested: tuple[int, ...] | None,
) -> tuple[dict[str, set[int]], dict[str, set[int]]]:
    if requested is None:
        editable = {name: set(records) for name, records in rows.items()}
    else:
        missing = set(requested) - rows["sites"].keys()
        if missing:
            raise WorkbookExportError(
                "sites", min(missing), "site_id", "selected site does not exist",
            )
        editable = {name: set() for name in rows}
        editable["sites"] = set(requested)
        for name, field, target in (
            ("locations", "site_id", "sites"),
            ("location_labels", "location_id", "locations"),
            ("deployments", "location_id", "locations"),
            ("interfaces", "deployment_id", "deployments"),
        ):
            editable[name] = {
                key for key, row in rows[name].items()
                if row[field] in editable[target]
            }

    selected = {name: ids.copy() for name, ids in editable.items()}
    pending = deque(
        (name, key) for name, ids in selected.items() for key in sorted(ids)
    )
    while pending:
        name, key = pending.popleft()
        for column in get_sheet_spec(name).fields:
            if column.kind != CellKind.REFERENCE:
                continue
            field = f"{column.name}_id"
            value = rows[name][key][field]
            if value is None and column.nullable:
                continue
            target = column.target_sheet
            if not _valid_id(value) or value not in rows[target]:
                raise WorkbookExportError(name, key, field, "missing or invalid referenced ID")
            if value not in selected[target]:
                selected[target].add(value)
                pending.append((target, value))

    # Site ancestors are the only recursively self-referencing resource here.
    complete = set()
    for key in sorted(selected["sites"]):
        path = set()
        current = key
        while current is not None and current not in complete:
            if current in path:
                raise WorkbookExportError("sites", current, "parent_id", "ancestor cycle")
            path.add(current)
            current = rows["sites"][current]["parent_id"]
        complete.update(path)
    return selected, editable


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("expected nonblank text without surrounding whitespace")
    if len(value) > 32767:
        raise ValueError("text exceeds Excel's 32767-character cell limit")
    if any(
        (ord(character) < 32 and character not in "\t\n\r")
        or 0xD800 <= ord(character) <= 0xDFFF
        or ord(character) in {0xFFFE, 0xFFFF}
        for character in value
    ):
        raise ValueError("text contains characters unsupported by XLSX")
    return value


def _timestamp(value: object) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None or pd.isna(value):
        raise ValueError("expected a timezone-aware timestamp")
    return value.astimezone(timezone.utc)


def _value(value: object, column: ColumnSpec) -> object:
    if value is None:
        if column.nullable:
            return None
        raise ValueError("required value is null")
    if column.kind == CellKind.TEXT:
        return _text(value)
    if column.kind == CellKind.NUMBER:
        if type(value) not in {int, float} or not math.isfinite(value):
            raise ValueError("expected a finite number")
        return value
    if column.kind == CellKind.BOOLEAN:
        if type(value) is not bool:
            raise ValueError("expected TRUE or FALSE")
        return value
    if column.kind == CellKind.TIMESTAMP:
        return _timestamp(value).isoformat().replace("+00:00", "Z")
    if column.kind == CellKind.JSON:
        if not isinstance(value, dict):
            raise ValueError("reader_options must be a JSON object")
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if json.loads(encoded) != value:
            raise ValueError("reader_options contains non-JSON values")
        return _text(encoded)
    raise ValueError(f"unsupported scalar kind: {column.kind}")


def _prepare_row(name: str, key: int, row: dict, editable: bool) -> dict:
    spec = get_sheet_spec(name)
    result = {
        spec.id_column: str(key), "ref": f"{spec.resource_type}_{key}",
        "row_role": "edit" if editable else "reference",
    }
    if name == "files":
        reader = row["reader_config"]
        if not isinstance(reader, dict) or set(reader) != {"reader", "options"}:
            raise WorkbookExportError(
                name, key, "reader_config", "expected exactly reader and options keys",
            )
        if reader["reader"] != "csv":
            raise WorkbookExportError(name, key, "reader_config", "only the csv reader is supported")
        row = {
            **row, "path": row["filepath"],
            "reader_type": reader["reader"], "reader_options": reader["options"],
        }
    for column in spec.fields:
        if name == "location_labels" and column.name == "is_initial":
            result[column.name] = False  # Assigned from the complete selected history below.
        elif column.kind == CellKind.REFERENCE:
            value = row[f"{column.name}_id"]
            target = get_sheet_spec(column.target_sheet)
            result[column.name] = None if value is None else f"{target.resource_type}_{value}"
        else:
            try:
                result[column.name] = _value(row[column.name], column)
            except (TypeError, ValueError, OverflowError) as error:
                raise WorkbookExportError(name, key, column.name, str(error)) from error
    return result


def prepare_workbook_export(
    frames: Mapping[str, pd.DataFrame], *, site_ids: Sequence[int] | None = None,
) -> WorkbookExport:
    """Prepare full or site-scoped workbook frames without IO or input mutation.

    None selects all records. A nonempty sequence selects exact site IDs, with
    required related records marked as references. Duplicated requested IDs are
    deduplicated and sorted. All source structures/primary IDs are checked;
    relationships and cell values are checked within the selected closure.

    This checks representability and references, not complete CONFIG semantics
    or whether a future apply will succeed. No YAML or XLSX file is produced.
    """
    requested = None
    if site_ids is not None:
        try:
            requested = tuple(site_ids)
        except TypeError as error:
            raise ValueError("site_ids must be a nonempty sequence of positive integer IDs") from error
        if not requested or any(not _valid_id(key) for key in requested):
            raise ValueError("site_ids must be a nonempty sequence of positive integer IDs")
        requested = tuple(sorted(set(requested)))

    rows = _index_frames(frames)
    selected, editable = _select_rows(rows, requested)
    prepared = {
        name: {
            key: _prepare_row(name, key, rows[name][key], key in editable[name])
            for key in sorted(ids)
        }
        for name, ids in selected.items()
    }

    histories: dict[int, list[int]] = {}
    for key in selected["location_labels"]:
        location_id = rows["location_labels"][key]["location_id"]
        histories.setdefault(location_id, []).append(key)
    for location_id in sorted(selected["locations"]):
        history = histories.get(location_id, [])
        if not history:
            raise WorkbookExportError(
                "locations", location_id, "initial_label", "location has no label history",
            )
        initial = min(history, key=lambda key: (
            _timestamp(rows["location_labels"][key]["valid_from"]), key,
        ))
        prepared["location_labels"][initial]["is_initial"] = True

    return WorkbookExport(
        scope="all" if requested is None else "sites",
        site_ids=() if requested is None else requested,
        frames={
            spec.name: pd.DataFrame(
                list(prepared[spec.name].values()), columns=spec.headers, dtype=object,
            )
            for spec in RESOURCE_SHEETS
        },
    )
