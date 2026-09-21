"""Create an empty CONFIG workbook using the versioned sheet contract."""

from io import BytesIO
from pathlib import Path
from uuid import uuid4

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from .schema import (
    FORMAT_VERSION,
    GUIDE_SHEET,
    INFO_HEADERS,
    INFO_KEYS,
    INFO_SHEET,
    RESOURCE_SHEETS,
    ROW_ROLES,
    CellKind,
    SheetSpec,
)

_TEXT_KINDS = {
    CellKind.TEXT, CellKind.ID, CellKind.TIMESTAMP,
    CellKind.JSON, CellKind.REFERENCE,
}
_LAST_EXCEL_ROW = 1_048_576
_HEADER_FILL = PatternFill("solid", fgColor="234E52")
_HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF")


def _write_text(sheet: Worksheet, row: int, column: int, value: str) -> None:
    """Write literal text, including strings that Excel could read as formulas."""
    cell = sheet.cell(row, column, value)
    cell.data_type = "s"
    cell.number_format = "@"


def _format_headers(sheet: Worksheet) -> None:
    for cell in sheet[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    sheet.row_dimensions[1].height = 32
    sheet.freeze_panes = "A2"


def _add_dropdown(sheet: Worksheet, column: int, choices: tuple[str, ...]) -> None:
    letter = get_column_letter(column)
    validation = DataValidation(
        type="list",
        formula1='"' + ",".join(choices) + '"',
        allow_blank=True,
        showDropDown=False,
        showErrorMessage=True,
        errorStyle="stop",
        errorTitle="Choose a listed value",
        error="Use one of the values in the dropdown.",
    )
    validation.add(f"{letter}2:{letter}{_LAST_EXCEL_ROW}")
    sheet.add_data_validation(validation)


def _add_resource_sheet(workbook: Workbook, spec: SheetSpec) -> None:
    sheet = workbook.create_sheet(spec.name)
    sheet.append(spec.headers)
    _format_headers(sheet)

    for index, column in enumerate(spec.columns, start=1):
        letter = get_column_letter(index)
        width = max(18, min(34, len(column.name) + 3))
        if column.name in {"description", "path", "reader_options"}:
            width = 48
        sheet.column_dimensions[letter].width = width
        if column.kind in _TEXT_KINDS:
            # Column defaults help cells created later in Excel. Explicitly
            # format the first empty input row as well, without adding values.
            sheet.column_dimensions[letter].number_format = "@"
            sheet.cell(2, index).number_format = "@"
        if column.name == "row_role":
            _add_dropdown(sheet, index, ROW_ROLES)
        elif column.kind == CellKind.BOOLEAN:
            _add_dropdown(sheet, index, ("TRUE", "FALSE"))
        elif column.name == "reader_type":
            _add_dropdown(sheet, index, ("csv",))


def _add_guide(workbook: Workbook, target_environment: str) -> None:
    sheet = workbook.active
    sheet.title = GUIDE_SHEET
    sheet.column_dimensions["A"].width = 110
    lines = (
        "DendroFlow control workbook",
        f"Target environment: {target_environment}",
        (
            "This empty template starts a new setup. For existing records, begin "
            "each editing session with a fresh database export."
        ),
        (
            "Enter records below row 1. Keep every resource sheet and its headers. "
            "Do not add totals, formulas, or explanatory rows inside resource tables."
        ),
        (
            "New rows: leave the database ID blank, enter a unique ref within the "
            "sheet, and choose row_role=edit. Do not invent database IDs."
        ),
        (
            "Relationship columns use the target sheet's ref. For example, "
            "sensors.sensor_model refers to sensor_models.ref."
        ),
        (
            "Fill required values. A blank nullable value requests null; it does "
            "not mean leave unchanged. Missing rows never request deletion."
        ),
        (
            "Use TRUE or FALSE for boolean fields. Enter identifiers as text "
            "to preserve leading zeros. Paste values without replacing cell formats."
        ),
        (
            "Use timestamp text with an explicit offset, for example "
            "2026-01-01T00:00:00Z. Do not use timezone-free Excel date values."
        ),
        (
            "Each new location needs one row in location_labels marked "
            "is_initial=TRUE. Use FALSE for additional labels."
        ),
        (
            "For files, use reader_type=csv and a JSON object in reader_options, "
            "such as {}. Every new file needs at least one interface."
        ),
        (
            "Version 1 cannot update existing files, interfaces, location labels, "
            "or a site's parent. Dropdowns and formatting are editing aids only."
        ),
        (
            "Template generation does not validate records or write to databases. "
            "Workbook import and change planning are implemented in later Phase G steps."
        ),
    )
    for row, value in enumerate(lines, start=1):
        _write_text(sheet, row, 1, value)
        sheet.cell(row, 1).alignment = Alignment(wrap_text=True, vertical="center")
        sheet.row_dimensions[row].height = 42
    _format_headers(sheet)


def write_workbook_template(
    path: str | Path,
    *,
    target_environment: str,
) -> Path:
    """Save a new, empty XLSX template without database access.

    The environment is an explicit, non-secret label, not a connection string.
    Parent directories must exist. Existing paths are never overwritten.
    Serialization finishes in memory before the output path is opened.
    This function does not promise an atomic save on filesystem failure.
    """
    if not isinstance(target_environment, str):
        raise TypeError("target_environment must be a string")
    environment = target_environment.strip()
    if not environment or len(environment) > 128:
        raise ValueError("target_environment must contain 1 to 128 characters")
    if any(ord(character) < 32 for character in environment):
        raise ValueError("target_environment must not contain control characters")

    destination = Path(path)
    if destination.suffix.lower() != ".xlsx":
        raise ValueError("workbook template path must end with .xlsx")

    workbook = Workbook()
    try:
        _add_guide(workbook, environment)
        info = workbook.create_sheet(INFO_SHEET)
        info.append(INFO_HEADERS)
        values = {
            "format_version": FORMAT_VERSION,
            "workbook_id": str(uuid4()),
            "target_environment": environment,
            "exported_at": None,
            "scope": "template",
            "site_ids": "[]",
        }
        for row, key in enumerate(INFO_KEYS, start=2):
            _write_text(info, row, 1, key)
            value = values[key]
            if isinstance(value, str):
                _write_text(info, row, 2, value)
            else:
                info.cell(row, 2, value)
        _format_headers(info)
        info.column_dimensions["A"].width = 24
        info.column_dimensions["B"].width = 52

        for spec in RESOURCE_SHEETS:
            _add_resource_sheet(workbook, spec)

        with BytesIO() as buffer:
            workbook.save(buffer)
            with destination.open("xb") as output:
                output.write(buffer.getvalue())
    finally:
        workbook.close()

    return destination
