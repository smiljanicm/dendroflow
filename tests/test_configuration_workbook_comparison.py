from copy import deepcopy
from dataclasses import replace
from datetime import timedelta, timezone

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from dendroflow.configuration.workbook.comparison import (
    ComparisonStatus,
    WorkbookComparisonError,
    WorkbookReference,
    compare_workbook,
)
from dendroflow.configuration.workbook.matching import match_workbook
from dendroflow.configuration.workbook.parsing import parse_workbook
from dendroflow.configuration.workbook.preparation import prepare_workbook_export
from dendroflow.configuration.workbook.reader import read_workbook
from dendroflow.configuration.workbook.schema import (
    RESOURCE_SHEETS,
    CellKind,
    get_sheet_spec,
)
from dendroflow.configuration.workbook.writer import write_workbook_export

from . import test_configuration_workbook_validation as helpers


@pytest.fixture
def source():
    return helpers.source.__wrapped__()


def compare(parsed, source):
    return compare_workbook(match_workbook(parsed, source))


def alternate(source, sheet):
    """Add another current identity to exercise a real relationship change."""
    spec = get_sheet_spec(sheet)
    frame = source[sheet]
    row = deepcopy(frame.iloc[0].to_dict())
    key = row[spec.id_column] + 1000
    row[spec.id_column] = key
    frame.loc[len(frame)] = row
    if sheet == "locations":
        labels = source["location_labels"]
        label = deepcopy(labels.iloc[0].to_dict())
        label.update(location_label_id=1070, location_id=key)
        labels.loc[len(labels)] = label
    return f"{spec.resource_type}_{key}"


@pytest.mark.parametrize("scope", [None, [2], [1, 2, 3]])
def test_unchanged_saved_export_has_no_changes(source, tmp_path, scope):
    path = write_workbook_export(
        tmp_path / "control.xlsx", prepare_workbook_export(source, site_ids=scope),
        target_environment="local-dev",
    )
    parsed = parse_workbook(read_workbook(path, expected_environment="local-dev"))
    result = compare(parsed, source)
    assert result.issues == ()
    assert result.raise_for_errors() is None
    for rows in result.rows.values():
        for row in rows:
            assert row.status == ComparisonStatus.UNCHANGED
            assert row.changes == ()


UPDATES = [(spec.name, column) for spec in RESOURCE_SHEETS for column in spec.update_columns]


@pytest.mark.parametrize(("sheet", "column"), UPDATES, ids=[f"{name}.{c.name}" for name, c in UPDATES])
def test_every_public_update_field_produces_a_located_difference(source, sheet, column):
    replacement = None
    if column.kind == CellKind.REFERENCE:
        replacement = alternate(source, column.target_sheet)
    parsed = helpers.parsed_export(source)
    before = parsed.frames[sheet].at[0, column.name]
    if column.kind == CellKind.TEXT:
        replacement = "Changed"
    elif column.kind == CellKind.NUMBER:
        replacement = 12.5
    elif column.kind == CellKind.BOOLEAN:
        replacement = not before
    elif column.kind == CellKind.TIMESTAMP:
        replacement = helpers.START + timedelta(days=1)
    parsed.frames[sheet].at[0, column.name] = replacement
    result = compare(parsed, source)
    row = result.rows[sheet][0]
    assert row.status == ComparisonStatus.UPDATE
    assert len(row.changes) == 1
    change = row.changes[0]
    assert change.field == column.name
    assert change.update_field == column.update_field
    assert change.coordinate == parsed.coordinates[sheet].at[0, column.name]
    assert not result.issues
    if column.kind == CellKind.REFERENCE:
        assert isinstance(change.before, WorkbookReference)
        assert isinstance(change.after, WorkbookReference)
        assert change.before.database_id != change.after.database_id
        assert change.before.ref is None and change.after.ref is None
    else:
        assert change.before == before
        assert change.after == replacement


UNSUPPORTED = [(spec.name, column) for spec in RESOURCE_SHEETS for column in spec.fields
               if column.update_field is None and column.name != "reader_type"]


@pytest.mark.parametrize(("sheet", "column"), UNSUPPORTED,
                         ids=[f"{name}.{c.name}" for name, c in UNSUPPORTED])
def test_every_unsupported_existing_field_blocks_conversion(source, sheet, column):
    replacement = None
    if column.kind == CellKind.REFERENCE:
        replacement = alternate(source, column.target_sheet)
    parsed = helpers.parsed_export(source)
    if column.kind == CellKind.TEXT:
        replacement = "Changed"
    elif column.kind == CellKind.TIMESTAMP:
        replacement = helpers.START + timedelta(days=1)
    elif column.kind == CellKind.BOOLEAN:
        replacement = False
    elif column.kind == CellKind.JSON:
        replacement = {"delimiter": ";"}
    # Keep G3 initial-label uniqueness while moving an existing label.
    if sheet == "location_labels" and column.name == "location":
        parsed.frames[sheet].at[2, "is_initial"] = False
    parsed.frames[sheet].at[0, column.name] = replacement
    result = compare(parsed, source)
    row = result.rows[sheet][0]
    assert row.status == ComparisonStatus.BLOCKED
    assert any(change.field == column.name and change.update_field is None for change in row.changes)
    assert any(issue.coordinate == parsed.coordinates[sheet].at[0, column.name]
               and "not supported" in issue.message for issue in row.issues)
    with pytest.raises(WorkbookComparisonError) as caught:
        result.raise_for_errors()
    assert caught.value.issues == result.issues


@pytest.mark.parametrize(("sheet", "field"), [
    ("sites", "name"), ("location_types", "description"), ("sensor_types", "type"),
    ("variables", "derived"), ("sensor_models", "manufacturer"),
    ("sensors", "serial_number"), ("files", "path"),
])
def test_changed_reference_rows_are_blocked_even_for_supported_update_fields(source, sheet, field):
    parsed = helpers.parsed_export(source, [2])
    parsed.frames[sheet].at[0, field] = True if field == "derived" else "Changed"
    row = compare(parsed, source).rows[sheet][0]
    assert row.status == ComparisonStatus.BLOCKED
    assert "reference rows" in row.issues[0].message


def test_alias_renames_and_row_column_reordering_are_semantic_noops(source):
    parsed = helpers.parsed_export(source)
    for spec in RESOURCE_SHEETS:
        parsed.frames[spec.name]["ref"] = parsed.frames[spec.name]["ref"].map(lambda alias: "new_" + alias)
        for column in spec.fields:
            if column.target_sheet:
                parsed.frames[spec.name][column.name] = parsed.frames[spec.name][column.name].map(
                    lambda alias: None if alias is None else "new_" + alias,
                )
        parsed.frames[spec.name] = parsed.frames[spec.name].iloc[::-1, ::-1]
        parsed.coordinates[spec.name] = parsed.coordinates[spec.name].iloc[::-1, ::-1]
    result = compare(parsed, source)
    assert all(row.status == ComparisonStatus.UNCHANGED for rows in result.rows.values() for row in rows)
    assert result.rows["sites"][0].match.coordinates["site_id"] == "A4"


def test_renaming_a_referenced_resource_changes_only_that_resource(source):
    parsed = helpers.parsed_export(source)
    parsed.frames["sites"].at[1, "site_code"] = "renamed_site"
    parsed.frames["variables"].at[0, "variable"] = "renamed_variable"
    result = compare(parsed, source)
    assert result.rows["sites"][1].status == ComparisonStatus.UPDATE
    assert result.rows["variables"][0].status == ComparisonStatus.UPDATE
    assert all(row.status == ComparisonStatus.UNCHANGED for row in result.rows["locations"])
    assert all(row.status == ComparisonStatus.UNCHANGED for row in result.rows["deployments"])


def test_diagnostic_retains_original_cell_after_reordering(source):
    parsed = helpers.parsed_export(source)
    parsed.frames["location_labels"].at[0, "label"] = "Changed"
    parsed.frames["location_labels"] = parsed.frames["location_labels"].iloc[::-1, ::-1]
    parsed.coordinates["location_labels"] = parsed.coordinates["location_labels"].iloc[::-1, ::-1]
    result = compare(parsed, source)
    assert result.issues[0].sheet == "location_labels"
    assert result.issues[0].coordinate == "E2"


def test_blank_nullable_fields_are_explicit_null_updates(source):
    source["sites"].at[1, "description"] = "Clear me"
    source["locations"].at[0, "height_above_ground"] = 0.0
    source["deployments"].at[0, "valid_to"] = helpers.START + timedelta(days=1)
    parsed = helpers.parsed_export(source)
    for sheet, index, field in [("sites", 1, "description"), ("locations", 0, "height_above_ground"),
                                ("deployments", 0, "valid_to")]:
        parsed.frames[sheet].at[index, field] = None
    result = compare(parsed, source)
    for sheet, index in [("sites", 1), ("locations", 0), ("deployments", 0)]:
        assert result.rows[sheet][index].changes[0].after is None
        assert result.rows[sheet][index].status == ComparisonStatus.UPDATE


def test_exact_numbers_false_and_offset_timestamps_do_not_create_noise(source):
    source["locations"].at[0, "height_above_ground"] = 0
    source["locations"].at[0, "latitude"] = 12.123456789012345
    source["deployments"].at[0, "valid_from"] = helpers.START.astimezone(timezone(timedelta(hours=2)))
    result = compare(helpers.parsed_export(source), source)
    assert all(row.status == ComparisonStatus.UNCHANGED for rows in result.rows.values() for row in rows)


def test_small_real_numeric_change_is_not_hidden_by_tolerance(source):
    source["locations"].at[0, "height_above_ground"] = 1.0
    parsed = helpers.parsed_export(source)
    parsed.frames["locations"].at[0, "height_above_ground"] = 1.0000000000000002
    assert compare(parsed, source).rows["locations"][0].status == ComparisonStatus.UPDATE


@pytest.mark.parametrize(("before", "after", "changed"), [
    ({"a": 1, "b": [True, None]}, {"b": [True, None], "a": 1}, False),
    ({"number": 1}, {"number": 1.0}, False),
    ({"value": True}, {"value": 1}, True),
    ({"nested": [{"value": False}]}, {"nested": [{"value": 0}]}, True),
    ({"list": [1, 2]}, {"list": [2, 1]}, True),
    ({"value": None}, {"value": "null"}, True),
])
def test_reader_options_compare_json_structure_without_boolean_number_coercion(source, before, after, changed):
    source["files"].at[0, "reader_config"]["options"] = before
    parsed = helpers.parsed_export(source)
    parsed.frames["files"].at[0, "reader_options"] = after
    row = compare(parsed, source).rows["files"][0]
    assert row.status == (ComparisonStatus.BLOCKED if changed else ComparisonStatus.UNCHANGED)


def test_omitted_initial_label_is_still_used_to_check_remaining_marker(source):
    labels = source["location_labels"]
    labels.loc[2] = [72, 60, "Later", helpers.START + timedelta(days=1), None]
    parsed = helpers.parsed_export(source)
    helpers.remove_rows(parsed, "location_labels", [0])
    assert compare(parsed, source).rows["location_labels"][1].status == ComparisonStatus.UNCHANGED
    parsed.frames["location_labels"].at[1, "is_initial"] = True
    row = compare(parsed, source).rows["location_labels"][1]
    assert row.status == ComparisonStatus.BLOCKED
    assert row.changes[0].field == "is_initial"


def test_initial_label_uses_timestamp_then_exact_id_and_current_history(source):
    parsed = helpers.parsed_export(source)
    source["location_labels"].loc[2] = [69, 60, "Earlier tie", helpers.START, None]
    row = compare(parsed, source).rows["location_labels"][0]
    assert row.status == ComparisonStatus.BLOCKED
    assert row.changes[0].before is False and row.changes[0].after is True


def test_new_rows_and_relationship_to_new_target_remain_unresolved_candidates(source):
    parsed = helpers.parsed_export(source)
    sensor = deepcopy(parsed.frames["sensors"].iloc[0].to_dict())
    sensor.update(sensor_id=None, ref="new_sensor")
    helpers.add_row(parsed, "sensors", sensor)
    parsed.frames["deployments"].at[0, "sensor"] = "new_sensor"
    result = compare(parsed, source)
    assert result.rows["sensors"][-1].status == ComparisonStatus.NEW
    assert result.rows["sensors"][-1].changes == ()
    change = result.rows["deployments"][0].changes[0]
    assert change.after == WorkbookReference("sensors", ref="new_sensor")
    assert change.before == WorkbookReference("sensors", database_id=50)
    assert result.rows["deployments"][0].status == ComparisonStatus.UPDATE


def test_template_classifies_all_declarations_as_new_and_empty_template_is_valid(source):
    parsed = helpers.parsed_export(source)
    parsed = replace(parsed, metadata=replace(parsed.metadata, scope="template", exported_at=None))
    for spec in RESOURCE_SHEETS:
        parsed.frames[spec.name][spec.id_column] = pd.Series([None] * len(parsed.frames[spec.name]), dtype=object)
    result = compare(parsed, source)
    assert all(row.status == ComparisonStatus.NEW for rows in result.rows.values() for row in rows)
    for name in parsed.frames:
        helpers.remove_rows(parsed, name, list(parsed.frames[name].index))
    assert all(rows == () for rows in compare(parsed, source).rows.values())


def test_omitted_rows_never_become_changes_or_deletions(source):
    parsed = helpers.parsed_export(source)
    helpers.remove_rows(parsed, "location_labels", [0, 1])
    result = compare(parsed, source)
    assert result.rows["location_labels"] == ()
    assert not result.issues
    assert all(row.status == ComparisonStatus.UNCHANGED for rows in result.rows.values() for row in rows)


@pytest.mark.parametrize(("sheet", "field", "bad"), [
    ("sites", "description", ""), ("sites", "name", " padded "),
    ("variables", "derived", 1), ("locations", "height_above_ground", float("nan")),
    ("deployments", "valid_from", helpers.START.replace(tzinfo=None)),
    ("files", "reader_config", {"reader": "csv", "options": {}, "extra": 1}),
    ("files", "reader_config", {"reader": "legacy", "options": {}}),
    ("files", "reader_config", {"reader": "csv", "options": {"tuple": (1, 2)}}),
])
def test_unrepresentable_current_values_block_instead_of_normalizing(source, sheet, field, bad):
    parsed = helpers.parsed_export(source)
    source[sheet].at[0, field] = bad
    result = compare(parsed, source)
    row = result.rows[sheet][0]
    assert row.status == ComparisonStatus.BLOCKED
    assert any("current database value cannot be compared" in issue.message for issue in row.issues)


def test_invalid_omitted_sibling_timestamp_blocks_initial_marker_comparison(source):
    parsed = helpers.parsed_export(source)
    source["location_labels"].loc[2] = [72, 60, "Bad timestamp", None, None]
    row = compare(parsed, source).rows["location_labels"][0]
    assert row.status == ComparisonStatus.BLOCKED
    assert "is_initial: current database value" in row.issues[0].message


def test_unrelated_bad_scalar_does_not_block_scoped_comparison(source):
    parsed = helpers.parsed_export(source, [2])
    source["sites"].at[2, "name"] = ""
    assert not compare(parsed, source).issues


def test_supported_and_blocked_changes_on_one_row_are_reported_together(source):
    parsed = helpers.parsed_export(source)
    parsed.frames["sites"].at[1, "name"] = "Rename"
    parsed.frames["sites"].at[1, "parent"] = None
    row = compare(parsed, source).rows["sites"][1]
    assert row.status == ComparisonStatus.BLOCKED
    assert [change.field for change in row.changes] == ["name", "parent"]
    assert len(row.issues) == 1


def test_bigint_relationships_are_compared_without_float_conversion(source):
    big = 2**63 - 1
    source["variables"].at[0, "variable_id"] = big
    source["deployments"]["variable_id"] = pd.Series([big, big], dtype=object)
    parsed = helpers.parsed_export(source)
    assert not compare(parsed, source).rows["deployments"][0].changes


def test_comparison_is_detached_preserves_inputs_and_performs_no_io(source, monkeypatch):
    source["files"].at[0, "reader_config"]["options"] = {"nested": [1]}
    parsed = helpers.parsed_export(source)
    parsed.frames["files"].at[0, "reader_options"] = {"nested": [2]}
    matched = match_workbook(parsed, source)
    before = deepcopy(matched.rows)
    frames = {name: frame.copy(deep=True) for name, frame in matched.parsed.frames.items()}
    def fail(*args, **kwargs):
        pytest.fail("comparison attempted external IO")
    monkeypatch.setattr("builtins.open", fail)
    monkeypatch.setattr("dendroflow.configuration.workbook.source.connect", fail)
    result = compare_workbook(matched)
    assert matched.rows == before
    for name, frame in frames.items():
        assert_frame_equal(matched.parsed.frames[name], frame)
    result.rows["files"][0].changes[0].before["nested"].append(3)
    result.rows["files"][0].changes[0].after["nested"].append(4)
    result.rows["files"][0].match.values["reader_options"]["nested"].append(5)
    assert matched.rows["files"][0].current["reader_config"]["options"] == {"nested": [1]}
    assert matched.rows["files"][0].values["reader_options"] == {"nested": [2]}


def test_report_order_is_schema_then_workbook_row_then_field(source):
    parsed = helpers.parsed_export(source)
    parsed.frames["files"].at[0, "path"] = "/changed"
    parsed.frames["location_labels"].at[0, "label"] = "Changed"
    parsed.frames["location_labels"].at[0, "is_initial"] = False
    result = compare(parsed, source)
    assert [(issue.sheet, issue.coordinate) for issue in result.issues] == [
        ("location_labels", "E2"), ("location_labels", "H2"), ("files", "D2"),
    ]


def test_requires_g4a_result():
    with pytest.raises(TypeError, match="MatchedWorkbook"):
        compare_workbook(None)
