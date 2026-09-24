"""Compare matched workbook fields without CONFIG planning or external IO."""

import json
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum

from .matching import MatchedWorkbook, WorkbookRowMatch
from .preparation import _timestamp, _value
from .reader import WorkbookIssue, WorkbookMetadata
from .schema import RESOURCE_SHEETS, CellKind, ColumnSpec


class ComparisonStatus(str, Enum):
    UNCHANGED = "unchanged"
    NEW = "new"
    UPDATE = "update"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class WorkbookReference:
    """An existing target ID, or an unresolved new declaration's sheet/ref.

    Existing targets deliberately omit the alias: renaming it has no effect
    on equality. New targets have no promised database identity yet.
    """

    sheet: str
    database_id: int | None = None
    ref: str | None = None

    def __post_init__(self) -> None:
        if (self.database_id is None) == (self.ref is None):
            raise ValueError("provide exactly one of database_id or ref")


@dataclass(frozen=True)
class WorkbookFieldChange:
    field: str
    coordinate: str
    update_field: str | None
    before: object
    after: object


@dataclass(frozen=True)
class WorkbookRowComparison:
    match: WorkbookRowMatch
    status: ComparisonStatus
    changes: tuple[WorkbookFieldChange, ...]
    issues: tuple[WorkbookIssue, ...]


class WorkbookComparisonError(ValueError):
    """The comparison contains blocking issues; conversion must stop."""

    def __init__(self, issues: tuple[WorkbookIssue, ...]):
        self.issues = issues
        super().__init__("; ".join(
            f"{issue.sheet or 'workbook'}"
            f"{'!' + issue.coordinate if issue.coordinate else ''}: {issue.message}"
            for issue in issues
        ))


@dataclass(frozen=True)
class WorkbookComparison:
    """A review report, not a CONFIG plan or permission to write.

    Rows follow schema and workbook order. Dictionaries remain caller-owned
    and mutable. Blocked rows retain their differences for review, but must
    never generate operations. Call raise_for_errors before later conversion.
    """

    metadata: WorkbookMetadata
    rows: dict[str, tuple[WorkbookRowComparison, ...]]

    @property
    def issues(self) -> tuple[WorkbookIssue, ...]:
        return tuple(issue for rows in self.rows.values() for row in rows for issue in row.issues)

    def raise_for_errors(self) -> None:
        if self.issues:
            raise WorkbookComparisonError(self.issues)


def _json_equal(left: object, right: object) -> bool:
    """Compare JSON structures, keeping booleans distinct from JSON numbers."""
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_json_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    return left == right


class _Comparison:
    def __init__(self, matched: MatchedWorkbook):
        self.matched = matched
        self.references = {
            name: {
                row.values["ref"]: WorkbookReference(
                    name, row.database_id,
                    row.values["ref"] if row.database_id is None else None,
                ) for row in rows
            } for name, rows in matched.rows.items()
        }
        self.histories: dict[int, list[dict]] = {}
        for row in matched.current["location_labels"].values():
            self.histories.setdefault(row["location_id"], []).append(row)
        self.initials: dict[int, int] = {}

    def initial_label(self, location_id: int) -> int:
        if location_id not in self.initials:
            history = self.histories.get(location_id, ())
            if not history:
                raise ValueError("location has no current label history")
            first = min(history, key=lambda row: (
                _timestamp(row["valid_from"]), row["location_label_id"],
            ))
            self.initials[location_id] = first["location_label_id"]
        return self.initials[location_id]

    def current_value(self, name: str, row: dict, column: ColumnSpec) -> object:
        field = column.name
        if column.kind == CellKind.REFERENCE:
            key = row[f"{field}_id"]
            return None if key is None else WorkbookReference(column.target_sheet, key)
        if name == "location_labels" and field == "is_initial":
            return row["location_label_id"] == self.initial_label(row["location_id"])
        if name == "files" and field in {"reader_type", "reader_options"}:
            config = row["reader_config"]
            if not isinstance(config, dict) or set(config) != {"reader", "options"}:
                raise ValueError("reader_config must contain exactly reader and options")
            if config["reader"] != "csv":
                raise ValueError("only the csv reader is supported")
            value = config["reader" if field == "reader_type" else "options"]
        else:
            value = row["filepath" if name == "files" and field == "path" else field]

        # Reuse export representability checks without regenerating a workbook.
        # Do not strip database text or coerce invalid nulls/types into equality.
        prepared = _value(value, column)
        if value is None:
            return None
        if column.kind == CellKind.TIMESTAMP:
            return _timestamp(value)
        if column.kind == CellKind.JSON:
            return json.loads(prepared)
        return prepared

    def compare_row(self, name: str, row: WorkbookRowMatch, fields: tuple[ColumnSpec, ...]):
        if row.database_id is None:
            return WorkbookRowComparison(deepcopy(row), ComparisonStatus.NEW, (), ())
        changes = []
        issues = []
        for column in fields:
            field = column.name
            coordinate = row.coordinates[field]
            try:
                before = self.current_value(name, row.current, column)
            except (TypeError, ValueError, OverflowError, RecursionError) as error:
                issues.append(WorkbookIssue(
                    name, coordinate, f"{field}: current database value cannot be compared: {error}",
                ))
                continue
            after = row.values[field]
            if column.kind == CellKind.REFERENCE and after is not None:
                after = self.references[column.target_sheet][after]
            equal = _json_equal(before, after) if column.kind == CellKind.JSON else before == after
            if equal:
                continue
            changes.append(WorkbookFieldChange(
                field, coordinate, column.update_field, deepcopy(before), deepcopy(after),
            ))
            if row.expected_role == "reference":
                reason = "reference rows must match current database values"
            elif column.update_field is None:
                reason = "changes to this existing field are not supported"
            else:
                continue
            issues.append(WorkbookIssue(name, coordinate, f"{field}: {reason}"))

        status = ComparisonStatus.UNCHANGED
        if issues:
            status = ComparisonStatus.BLOCKED
        elif changes:
            status = ComparisonStatus.UPDATE
        return WorkbookRowComparison(deepcopy(row), status, tuple(changes), tuple(issues))


def compare_workbook(matched: MatchedWorkbook) -> WorkbookComparison:
    """Classify an unmodified G4.a result; perform no file/database IO.

    NEW means a declaration candidate; compatible-resource reuse is unresolved.
    UPDATE means fields exposed by the public CONFIG update contract changed;
    CONFIG validation, selector verification and planning still follow. New
    relationship targets remain sheet/ref identities until those later steps.

    Blocked differences and malformed current values are collected in the
    report. Missing rows never become deletions. This compares to the supplied
    current snapshot, not the export-time state, and does not check freshness.
    """
    if not isinstance(matched, MatchedWorkbook):
        raise TypeError("matched must be a MatchedWorkbook from G4.a matching")
    comparison = _Comparison(matched)
    return WorkbookComparison(matched.parsed.metadata, {
        spec.name: tuple(
            comparison.compare_row(spec.name, row, spec.fields)
            for row in matched.rows[spec.name]
        ) for spec in RESOURCE_SHEETS
    })
