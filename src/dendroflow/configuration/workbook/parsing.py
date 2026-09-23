"""Parse resource cells into typed values, retaining Excel source coordinates."""

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from .reader import WorkbookCell, WorkbookDocument, WorkbookIssue, WorkbookMetadata
from .schema import RESOURCE_SHEETS, ROW_ROLES, CellKind, ColumnSpec

_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])",
)


class WorkbookParseError(ValueError):
    """Invalid resource cells, collected without returning partial frames."""

    def __init__(self, issues: tuple[WorkbookIssue, ...]):
        self.issues = issues
        super().__init__("; ".join(
            f"{issue.sheet or 'workbook'}"
            f"{'!' + issue.coordinate if issue.coordinate else ''}: {issue.message}"
            for issue in issues
        ))


@dataclass(frozen=True)
class ParsedWorkbook:
    """Cell-parsed values; relationship and CONFIG validation are still required.

    Each caller-owned frame uses object dtype and schema column order. Rows use
    a fresh positional index in workbook order. coordinates[name].loc[i, column]
    identifies the original Excel cell for frames[name].loc[i, column].
    """

    metadata: WorkbookMetadata
    frames: dict[str, pd.DataFrame]
    coordinates: dict[str, pd.DataFrame]


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("expected text; numeric/date/boolean cells are not converted to text")
    if len(value) > 32767 or any(
        (ord(character) < 32 and character not in "\t\n\r")
        or 0xD800 <= ord(character) <= 0xDFFF
        or ord(character) in {0xFFFE, 0xFFFF}
        for character in value
    ):
        raise ValueError("text exceeds the XLSX cell limit or contains unsupported characters")
    return value


def _id(value: object) -> int:
    if (
        not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", value)
        or int(value) >= 2**63
    ):
        raise ValueError("expected a positive BIGINT ID as decimal text, without leading zeros")
    return int(value)


def _number(value: object) -> float:
    if isinstance(value, str):
        if not _NUMBER.fullmatch(value):
            raise ValueError("expected decimal text with a dot separator or a finite number")
    elif type(value) not in {int, float}:
        raise ValueError("expected a finite number, not a boolean or date")
    try:
        result = float(value)
    except (ValueError, OverflowError) as error:
        raise ValueError("number is outside the supported finite range") from error
    if not math.isfinite(result):
        raise ValueError("number must be finite")
    if isinstance(value, str) and result == 0.0 and any(
        digit in "123456789" for digit in value.lower().split("e", 1)[0]
    ):
        raise ValueError("nonzero number is too small to represent without loss")
    return result


def _boolean(value: object) -> bool:
    if type(value) is bool:
        return value
    if isinstance(value, str) and value.upper() in {"TRUE", "FALSE"}:
        return value.upper() == "TRUE"
    raise ValueError("expected TRUE or FALSE, not 0/1 or yes/no")


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise ValueError("expected ISO 8601 timestamp text with seconds and an explicit timezone offset")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError) as error:
        raise ValueError("invalid timestamp or UTC instant outside the supported range") from error


def _json_object(value: object) -> dict:
    def unique_keys(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("JSON object contains duplicate keys")
            result[key] = item
        return result

    def reject_constant(_):
        raise ValueError("JSON numbers must be finite")

    try:
        result = json.loads(
            _text(value), object_pairs_hook=unique_keys,
            parse_constant=reject_constant, parse_float=_number,
        )
        if not isinstance(result, dict):
            raise TypeError("expected a JSON object, not an array or scalar")
        # Decode escaped Unicode before checking representability. Escaped
        # control characters stay escaped on re-encoding and remain valid JSON.
        json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except RecursionError as error:
        raise ValueError("JSON nesting is too deep") from error
    return result


def _value(cell: WorkbookCell, column: ColumnSpec) -> object:
    # Calc can save literal booleans as TRUE()/FALSE() formulas. Recognize
    # only these two constants in boolean fields, without using cached results
    # or evaluating expressions. All other formulas remain invalid.
    if cell.data_type == "f":
        if column.kind == CellKind.BOOLEAN and isinstance(cell.value, str):
            constant = cell.value.strip().upper()
            if constant in {"=TRUE()", "=FALSE()"}:
                return constant == "=TRUE()"
        raise ValueError("formulas are not supported; enter a literal value")
    if cell.data_type == "e":
        raise ValueError("Excel error cells are not supported")
    if cell.data_type == "d":
        raise ValueError("Excel date/time cells are not supported; use explicit timestamp text")
    if cell.data_type not in {"s", "inlineStr", "n", "b"}:
        raise ValueError("unsupported Excel cell type")
    value = cell.value.strip() if isinstance(cell.value, str) else cell.value
    if value is None or (isinstance(value, str) and not value):
        if column.nullable:
            return None
        raise ValueError("required value is blank")
    parsers = {
        CellKind.TEXT: _text,
        CellKind.REFERENCE: _text,
        CellKind.ID: _id,
        CellKind.NUMBER: _number,
        CellKind.BOOLEAN: _boolean,
        CellKind.TIMESTAMP: _timestamp,
        CellKind.JSON: _json_object,
    }
    parsed = parsers[column.kind](value)
    if column.name == "row_role" and parsed not in ROW_ROLES:
        raise ValueError("row_role must be edit or reference")
    if column.name == "reader_type" and parsed != "csv":
        raise ValueError("only reader_type=csv is supported")
    return parsed


def parse_workbook(document: WorkbookDocument) -> ParsedWorkbook:
    """Parse an unmodified read_workbook result without database or file IO.

    Formulas except boolean TRUE()/FALSE() constants, errors and Excel dates
    are rejected. Text is trimmed and blanks become
    None only for nullable columns. IDs remain exact integers, numeric fields
    become finite floats, and aware timestamp text becomes UTC datetimes.
    Cell failures are collected in schema/row/column order. Full validation,
    relationship resolution, scope authorization and database comparison follow
    in later steps; successful parsing does not authorize an apply.
    """
    if not isinstance(document, WorkbookDocument):
        raise TypeError("document must be a WorkbookDocument from read_workbook")
    if set(document.sheets) != {spec.name for spec in RESOURCE_SHEETS}:
        raise WorkbookParseError((WorkbookIssue(None, None, "expected all eleven resource sheets"),))
    frames = {}
    coordinates = {}
    issues = []
    for spec in RESOURCE_SHEETS:
        values = []
        locations = []
        for row in document.sheets[spec.name]:
            if set(row) != set(spec.headers) or any(not isinstance(cell, WorkbookCell) for cell in row.values()):
                raise WorkbookParseError((WorkbookIssue(spec.name, None, "invalid raw row structure"),))
            parsed = {}
            for column in spec.columns:
                cell = row[column.name]
                try:
                    parsed[column.name] = _value(cell, column)
                except (ValueError, TypeError) as error:
                    issues.append(WorkbookIssue(spec.name, cell.coordinate, f"{column.name}: {error}"))
            values.append(parsed)
            locations.append({name: row[name].coordinate for name in spec.headers})
        frames[spec.name] = pd.DataFrame(values, columns=spec.headers, dtype=object)
        coordinates[spec.name] = pd.DataFrame(locations, columns=spec.headers, dtype=object)
    if issues:
        raise WorkbookParseError(tuple(issues))
    return ParsedWorkbook(document.metadata, frames, coordinates)
