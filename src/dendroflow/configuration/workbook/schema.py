"""Versioned sheet structure shared by future workbook readers and exporters.

This module checks headers only. Column kinds, nullability, and update fields
describe the contract; they do not validate cells or authorize database writes.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

FORMAT_VERSION = 1
GUIDE_SHEET = "guide"
INFO_SHEET = "workbook_info"
INFO_HEADERS = ("key", "value")
ROW_ROLES = ("edit", "reference")
EXPORT_SCOPES = ("all", "sites", "template")
INFO_KEYS = (
    "format_version", "workbook_id", "target_environment", "exported_at",
    "scope", "site_ids",
)


class CellKind(str, Enum):
    TEXT = "text"
    ID = "id"
    NUMBER = "number"
    BOOLEAN = "boolean"
    TIMESTAMP = "timestamp"
    JSON = "json"
    REFERENCE = "reference"


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    kind: CellKind = CellKind.TEXT
    nullable: bool = False
    target_sheet: str | None = None
    update_field: str | None = None


@dataclass(frozen=True)
class SheetSpec:
    name: str
    resource_type: str
    id_column: str
    fields: tuple[ColumnSpec, ...]

    @property
    def columns(self) -> tuple[ColumnSpec, ...]:
        return (
            ColumnSpec(self.id_column, CellKind.ID, nullable=True),
            ColumnSpec("ref"),
            ColumnSpec("row_role"),
            *self.fields,
        )

    @property
    def headers(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    @property
    def update_columns(self) -> tuple[ColumnSpec, ...]:
        return tuple(column for column in self.fields if column.update_field)


RESOURCE_SHEETS = (
    SheetSpec("sites", "site", "site_id", (
        ColumnSpec("site_code", update_field="site_code"),
        ColumnSpec("name", update_field="name"),
        ColumnSpec("description", nullable=True, update_field="description"),
        ColumnSpec("latitude", CellKind.NUMBER, nullable=True, update_field="latitude"),
        ColumnSpec("longitude", CellKind.NUMBER, nullable=True, update_field="longitude"),
        ColumnSpec("parent", CellKind.REFERENCE, nullable=True, target_sheet="sites"),
    )),
    SheetSpec("location_types", "location_type", "location_type_id", (
        ColumnSpec("type", update_field="type"),
        ColumnSpec("description", nullable=True, update_field="description"),
    )),
    SheetSpec("sensor_types", "sensor_type", "sensor_type_id", (
        ColumnSpec("type", update_field="type"),
        ColumnSpec("description", nullable=True, update_field="description"),
    )),
    SheetSpec("variables", "variable", "variable_id", (
        ColumnSpec("variable", update_field="variable"),
        ColumnSpec("derived", CellKind.BOOLEAN, update_field="derived"),
        ColumnSpec("description", nullable=True, update_field="description"),
    )),
    SheetSpec("sensor_models", "sensor_model", "sensor_model_id", (
        ColumnSpec("manufacturer", update_field="manufacturer"),
        ColumnSpec("model", update_field="model"),
        ColumnSpec("sensor_type", CellKind.REFERENCE,
                   target_sheet="sensor_types", update_field="sensor_type"),
    )),
    SheetSpec("sensors", "sensor", "sensor_id", (
        ColumnSpec("serial_number", update_field="serial_number"),
        ColumnSpec("sensor_model", CellKind.REFERENCE,
                   target_sheet="sensor_models", update_field="sensor_model"),
        ColumnSpec("description", nullable=True, update_field="description"),
    )),
    SheetSpec("locations", "location", "location_id", (
        ColumnSpec("site", CellKind.REFERENCE,
                   target_sheet="sites", update_field="site"),
        ColumnSpec("location_type", CellKind.REFERENCE,
                   target_sheet="location_types", update_field="location_type"),
        ColumnSpec("latitude", CellKind.NUMBER, nullable=True, update_field="latitude"),
        ColumnSpec("longitude", CellKind.NUMBER, nullable=True, update_field="longitude"),
        ColumnSpec("height_above_ground", CellKind.NUMBER,
                   nullable=True, update_field="height_above_ground"),
        ColumnSpec("azimuth", CellKind.NUMBER, nullable=True, update_field="azimuth"),
    )),
    SheetSpec("location_labels", "location_label", "location_label_id", (
        ColumnSpec("location", CellKind.REFERENCE, target_sheet="locations"),
        ColumnSpec("label"),
        ColumnSpec("valid_from", CellKind.TIMESTAMP),
        ColumnSpec("valid_to", CellKind.TIMESTAMP, nullable=True),
        ColumnSpec("is_initial", CellKind.BOOLEAN),
    )),
    SheetSpec("deployments", "deployment", "deployment_id", (
        ColumnSpec("sensor", CellKind.REFERENCE,
                   target_sheet="sensors", update_field="sensor"),
        ColumnSpec("location", CellKind.REFERENCE,
                   target_sheet="locations", update_field="location"),
        ColumnSpec("variable", CellKind.REFERENCE,
                   target_sheet="variables", update_field="variable"),
        ColumnSpec("valid_from", CellKind.TIMESTAMP, update_field="valid_from"),
        ColumnSpec("valid_to", CellKind.TIMESTAMP, nullable=True, update_field="valid_to"),
    )),
    SheetSpec("files", "file", "file_id", (
        ColumnSpec("path"),
        ColumnSpec("timestamp_timezone"),
        ColumnSpec("timestamp_format"),
        ColumnSpec("reader_type"),
        ColumnSpec("reader_options", CellKind.JSON),
    )),
    SheetSpec("interfaces", "interface", "interface_id", (
        ColumnSpec("file", CellKind.REFERENCE, target_sheet="files"),
        ColumnSpec("deployment", CellKind.REFERENCE, target_sheet="deployments"),
        ColumnSpec("timestamp_column"),
        ColumnSpec("values_column"),
        ColumnSpec("unit"),
    )),
)

SHEET_NAMES = (
    GUIDE_SHEET, INFO_SHEET, *(sheet.name for sheet in RESOURCE_SHEETS),
)


def get_sheet_spec(name: str) -> SheetSpec:
    """Return a resource sheet's contract, with no fuzzy name matching."""
    for sheet in RESOURCE_SHEETS:
        if sheet.name == name:
            return sheet
    raise KeyError(name)


@dataclass(frozen=True)
class HeaderIssue:
    sheet: str
    column: str | None
    message: str


def collect_header_issues(
    headers_by_sheet: Mapping[str, Sequence[str]],
) -> tuple[HeaderIssue, ...]:
    """Check named headers without depending on Excel or pandas.

    The reader must preserve duplicate headers and reject non-text/blank
    headers before calling this function. Sheet and column order may vary.
    The optional guide is free text; all other sheets and headers are required.
    """
    issues: list[HeaderIssue] = []
    expected = {
        INFO_SHEET: INFO_HEADERS,
        **{sheet.name: sheet.headers for sheet in RESOURCE_SHEETS},
    }
    for name in sorted(set(headers_by_sheet) - set(SHEET_NAMES)):
        issues.append(HeaderIssue(name, None, "unknown sheet"))

    for name, required in expected.items():
        if name not in headers_by_sheet:
            issues.append(HeaderIssue(name, None, "missing sheet"))
            continue

        headers = tuple(headers_by_sheet[name])
        for column, count in sorted(Counter(headers).items()):
            if count > 1:
                issues.append(HeaderIssue(name, column, "duplicate column"))
        for column in required:
            if column not in headers:
                issues.append(HeaderIssue(name, column, "missing column"))
        for column in sorted(set(headers) - set(required)):
            issues.append(HeaderIssue(name, column, "unknown column"))

    return tuple(issues)
