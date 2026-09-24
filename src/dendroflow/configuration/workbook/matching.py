"""Match workbook rows against a fresh, read-only configuration snapshot."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass

import pandas as pd

from .parsing import ParsedWorkbook
from .preparation import WorkbookExportError, _index_frames, _select_rows
from .reader import WorkbookIssue
from .schema import RESOURCE_SHEETS
from .source import read_configuration_frames
from .validation import validate_workbook


class WorkbookMatchError(ValueError):
    """Current-state identity/scope errors; no partial match is returned."""

    def __init__(self, issues: tuple[WorkbookIssue, ...]):
        self.issues = issues
        super().__init__("; ".join(
            f"{issue.sheet or 'workbook'}"
            f"{'!' + issue.coordinate if issue.coordinate else ''}: {issue.message}"
            for issue in issues
        ))


@dataclass(frozen=True)
class WorkbookRowMatch:
    """One workbook row and its current identity, in workbook order.

    current is None for a blank ID (a declaration candidate, not a promised
    INSERT). Values and coordinates are detached, caller-owned dictionaries.
    current retains database column names and relationship IDs. expected_role
    comes from current scope membership, not the edited row_role value.
    """

    values: dict[str, object]
    coordinates: dict[str, str]
    database_id: int | None
    current: dict[str, object] | None
    expected_role: str


@dataclass(frozen=True)
class MatchedWorkbook:
    """Detached workbook plus current source rows for later field comparison.

    This is an in-memory comparison input, not a persisted baseline or an
    authorization to apply. Its dictionaries and DataFrames remain mutable.
    """

    parsed: ParsedWorkbook
    rows: dict[str, tuple[WorkbookRowMatch, ...]]
    current: dict[str, dict[int, dict[str, object]]]


def match_workbook(
    parsed: ParsedWorkbook, current_frames: Mapping[str, pd.DataFrame],
) -> MatchedWorkbook:
    """Validate and match against caller-supplied SOURCE_COLUMNS frames, no IO.

    Nonblank IDs must exist in their own current table. For site scope they
    must also belong to the current export closure: selected sites, owned
    records and required dependencies. Workbook relationships independently
    satisfy G3.c. Both current and proposed scope must therefore be valid.

    Reuse the export identity/relationship traversal, without export scalar
    conversion or initial-label requirements. Invalid source structure or
    required relationships raise WorkbookExportError; located workbook errors
    raise WorkbookMatchError. G3 errors propagate unchanged. No input mutation.
    """
    validate_workbook(parsed)
    current = deepcopy(_index_frames(current_frames))
    requested = parsed.metadata.site_ids if parsed.metadata.scope == "sites" else None
    try:
        selected, editable = _select_rows(current, requested)
    except WorkbookExportError as error:
        # A missing selected site can be located at its workbook ID cell.
        if error.sheet == "sites" and requested and error.database_id not in current["sites"]:
            issues = []
            for position, row in enumerate(parsed.frames["sites"].to_dict("records")):
                if row["site_id"] in set(requested) - current["sites"].keys():
                    issues.append(WorkbookIssue(
                        "sites", parsed.coordinates["sites"].iloc[position]["site_id"],
                        f"site_id: selected site {row['site_id']} does not exist in current database",
                    ))
            raise WorkbookMatchError(tuple(issues)) from error
        raise

    matches = {}
    issues = []
    for spec in RESOURCE_SHEETS:
        name = spec.name
        matches[name] = []
        for position, values in enumerate(parsed.frames[name].to_dict("records")):
            coordinates = parsed.coordinates[name].iloc[position].to_dict()
            key = values[spec.id_column]
            stored = current[name].get(key)
            role = "edit"
            if key is not None:
                problem = None
                if stored is None:
                    problem = f"ID {key} does not exist in current database"
                elif key not in selected[name]:
                    problem = f"ID {key} is outside the current selected-site scope"
                else:
                    role = "edit" if key in editable[name] else "reference"
                if problem:
                    issues.append(WorkbookIssue(
                        name, coordinates[spec.id_column], f"{spec.id_column}: {problem}",
                    ))
                    continue
            if values["row_role"] != role:
                issues.append(WorkbookIssue(
                    name, coordinates["row_role"],
                    f"row_role: current database scope requires {role}",
                ))
            matches[name].append(WorkbookRowMatch(
                deepcopy(values), dict(coordinates), key, deepcopy(stored), role,
            ))
    if issues:
        raise WorkbookMatchError(tuple(issues))
    # pandas deep copies alone do not detach nested JSON objects.
    detached = ParsedWorkbook(
        metadata=parsed.metadata,
        frames={name: pd.DataFrame(
            deepcopy(frame.to_dict("records")), columns=frame.columns,
            index=frame.index.copy(), dtype=object,
        ) for name, frame in parsed.frames.items()},
        coordinates={name: frame.copy(deep=True) for name, frame in parsed.coordinates.items()},
    )
    return MatchedWorkbook(detached, {name: tuple(rows) for name, rows in matches.items()}, current)


def read_workbook_matches(parsed: ParsedWorkbook) -> MatchedWorkbook:
    """Validate before IO, then match using fresh configured database reads.

    Uses read_configuration_frames' two independent read-only repeatable-read
    transactions. There is no cross-database atomic snapshot, no persisted
    export baseline and no database write. The workbook environment label must
    already have been checked by read_workbook(expected_environment=...). It
    does not select or authenticate database connections.
    """
    validate_workbook(parsed)
    return match_workbook(parsed, read_configuration_frames())
