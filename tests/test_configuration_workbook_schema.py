import pytest

from dendroflow.configuration.models import (
    DeploymentUpdateFieldsConfig,
    LocationTypeUpdateFieldsConfig,
    LocationUpdateFieldsConfig,
    SensorModelUpdateFieldsConfig,
    SensorTypeUpdateFieldsConfig,
    SensorUpdateFieldsConfig,
    SiteUpdateFieldsConfig,
    VariableUpdateFieldsConfig,
)
from dendroflow.configuration.workbook.schema import (
    GUIDE_SHEET,
    INFO_HEADERS,
    INFO_SHEET,
    RESOURCE_SHEETS,
    SHEET_NAMES,
    CellKind,
    HeaderIssue,
    collect_header_issues,
    get_sheet_spec,
)


def workbook_headers():
    return {
        INFO_SHEET: INFO_HEADERS,
        **{sheet.name: sheet.headers for sheet in RESOURCE_SHEETS},
    }


def test_complete_headers_are_accepted_without_optional_guide():
    assert collect_header_issues(workbook_headers()) == ()


def test_guide_is_free_text():
    headers = workbook_headers()
    headers[GUIDE_SHEET] = ("Instructions for editing",)
    assert collect_header_issues(headers) == ()


def test_sheet_and_column_reordering_is_accepted():
    reordered = {
        name: tuple(reversed(headers))
        for name, headers in reversed(tuple(workbook_headers().items()))
    }
    assert collect_header_issues(reordered) == ()


@pytest.mark.parametrize("name", [INFO_SHEET, "sites", "interfaces"])
def test_missing_sheet_is_reported(name):
    headers = workbook_headers()
    del headers[name]
    assert collect_header_issues(headers) == (
        HeaderIssue(name, None, "missing sheet"),
    )


def test_unknown_sheet_is_reported():
    headers = workbook_headers()
    headers["notes"] = ("comment",)
    assert collect_header_issues(headers) == (
        HeaderIssue("notes", None, "unknown sheet"),
    )


@pytest.mark.parametrize("column", ["site_id", "ref", "row_role", "description"])
def test_even_nullable_column_headers_are_required(column):
    headers = workbook_headers()
    headers["sites"] = tuple(h for h in headers["sites"] if h != column)
    assert collect_header_issues(headers) == (
        HeaderIssue("sites", column, "missing column"),
    )


def test_duplicate_header_is_reported_before_dataframe_name_mangling():
    headers = workbook_headers()
    headers["sites"] += ("name",)
    assert collect_header_issues(headers) == (
        HeaderIssue("sites", "name", "duplicate column"),
    )


@pytest.mark.parametrize("column", ["Name", " name ", "site_name"])
def test_misspelled_headers_are_not_silently_normalized(column):
    headers = workbook_headers()
    headers["sites"] = tuple(column if h == "name" else h for h in headers["sites"])
    assert collect_header_issues(headers) == (
        HeaderIssue("sites", "name", "missing column"),
        HeaderIssue("sites", column, "unknown column"),
    )


def test_multiple_issues_are_returned_in_one_pass():
    headers = workbook_headers()
    headers["sites"] += ("name", "typo")
    del headers["files"]
    assert collect_header_issues(headers) == (
        HeaderIssue("sites", "name", "duplicate column"),
        HeaderIssue("sites", "typo", "unknown column"),
        HeaderIssue("files", None, "missing sheet"),
    )


@pytest.mark.parametrize("name", ["Sites", "unknown", GUIDE_SHEET, INFO_SHEET])
def test_resource_lookup_requires_an_exact_resource_sheet_name(name):
    with pytest.raises(KeyError):
        get_sheet_spec(name)


@pytest.mark.parametrize(("name", "model"), [
    ("sites", SiteUpdateFieldsConfig),
    ("location_types", LocationTypeUpdateFieldsConfig),
    ("sensor_types", SensorTypeUpdateFieldsConfig),
    ("variables", VariableUpdateFieldsConfig),
    ("sensor_models", SensorModelUpdateFieldsConfig),
    ("sensors", SensorUpdateFieldsConfig),
    ("locations", LocationUpdateFieldsConfig),
    ("deployments", DeploymentUpdateFieldsConfig),
])
def test_update_columns_match_public_yaml_update_contract(name, model):
    columns = get_sheet_spec(name).update_columns
    assert {column.update_field for column in columns} == set(model.model_fields)
    assert len(columns) == len(model.model_fields)
    for column in columns:
        assert column.nullable == (column.update_field not in model.non_nullable_fields)


@pytest.mark.parametrize("name", ["location_labels", "files", "interfaces"])
def test_create_reuse_only_resources_expose_no_update_columns(name):
    assert get_sheet_spec(name).update_columns == ()


def test_site_parent_remains_create_only_at_yaml_boundary():
    parent = next(c for c in get_sheet_spec("sites").fields if c.name == "parent")
    assert parent.target_sheet == "sites"
    assert parent.nullable
    assert parent.update_field is None


def test_all_references_target_existing_sheet_contracts():
    for sheet in RESOURCE_SHEETS:
        for column in sheet.columns:
            if column.kind == CellKind.REFERENCE:
                assert column.target_sheet is not None
                assert "ref" in get_sheet_spec(column.target_sheet).headers
            else:
                assert column.target_sheet is None


def test_schema_names_are_unique_and_excel_compatible():
    assert len(SHEET_NAMES) == len({name.casefold() for name in SHEET_NAMES})
    for name in SHEET_NAMES:
        assert 0 < len(name) <= 31
        assert not set(name) & set("[]:*?/\\")
    for sheet in RESOURCE_SHEETS:
        assert len(sheet.headers) == len(set(sheet.headers))
        ids = [column for column in sheet.columns if column.kind == CellKind.ID]
        assert len(ids) == 1
        assert ids[0].name == sheet.id_column
        assert ids[0].nullable
        assert ids[0].update_field is None
