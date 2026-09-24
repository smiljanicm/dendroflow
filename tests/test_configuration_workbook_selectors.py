from copy import deepcopy
from dataclasses import replace
from datetime import timedelta, timezone

import pandas as pd
import pytest

from dendroflow.configuration import metadata
from dendroflow.configuration.models import ConfigModel
from dendroflow.configuration.resolution import selectors as config_selectors
from dendroflow.configuration.resolution.aliases import build_alias_registry
from dendroflow.configuration.resolution.metadata import (
    resolve_deployment_reference_aliases,
    resolve_location_reference_aliases,
    resolve_sensor_model_reference_aliases,
    resolve_sensor_reference_aliases,
    resolve_simple_reference_aliases,
)
from dendroflow.configuration.workbook.comparison import WorkbookComparisonError
from dendroflow.configuration.workbook.matching import match_workbook
from dendroflow.configuration.workbook.schema import RESOURCE_SHEETS, get_sheet_spec
from dendroflow.configuration.workbook.selectors import (
    WorkbookSelectorError,
    build_workbook_selectors,
)

from . import test_configuration_workbook_validation as helpers


@pytest.fixture
def source():
    return helpers.source.__wrapped__()


def build(parsed, source):
    return build_workbook_selectors(match_workbook(parsed, source)).selectors


def dumps(result):
    return {sheet: {key: (row.alias, row.lookup.model_dump(exclude_none=True), row.dependencies, row.helper)
                    for key, row in rows.items()} for sheet, rows in result.items()}


EXPECTED = {
    "sites": (2, {"site_code": "north"}),
    "location_types": (10, {"type": "well"}),
    "sensor_types": (20, {"type": "logger"}),
    "variables": (30, {"variable": "level"}),
    "sensor_models": (40, {"manufacturer": "Maker", "model": "Model"}),
    "sensors": (50, {"serial_number": "000001", "sensor_model": "sensor_model_40"}),
    "locations": (60, {"site": "site_2", "initial_label": "North"}),
    "deployments": (80, {"sensor": "sensor_50", "location": "location_60", "variable": "variable_30",
                         "valid_from": helpers.START}),
    "files": (90, {"path": "/data/shared.csv"}),
}


@pytest.mark.parametrize("sheet", list(EXPECTED))
def test_each_public_lookup_contains_current_full_identity_only(source, sheet):
    result = build(helpers.parsed_export(source), source)
    key, expected = EXPECTED[sheet]
    selector = result[sheet][key]
    assert selector.lookup.model_dump(exclude_none=True) == expected
    assert selector.database_id == key
    assert selector.helper is False
    assert selector.alias == f"{get_sheet_spec(sheet).resource_type}_{key}"
    assert not any(field.endswith("_id") for field in selector.lookup.model_dump())


@pytest.mark.parametrize("selection", [None, [2], [1, 2, 3]])
def test_unchanged_workbook_builds_lookupable_rows_only(source, selection):
    parsed = helpers.parsed_export(source, selection)
    result = build(parsed, source)
    assert "location_labels" not in result and "interfaces" not in result
    assert sum(map(len, result.values())) == sum(len(parsed.frames[sheet]) for sheet in EXPECTED)


@pytest.mark.parametrize(("sheet", "field"), [
    ("sites", "site_code"), ("location_types", "type"), ("sensor_types", "type"),
    ("variables", "variable"), ("sensor_models", "manufacturer"),
    ("sensor_models", "model"), ("sensors", "serial_number"), ("deployments", "valid_from"),
])
def test_renames_and_date_changes_select_original_values(source, sheet, field):
    parsed = helpers.parsed_export(source)
    parsed.frames[sheet].at[0, field] = helpers.START + timedelta(days=1) if field == "valid_from" else "Renamed"
    result = build(parsed, source)
    key = parsed.frames[sheet].iloc[0][get_sheet_spec(sheet).id_column]
    assert getattr(result[sheet][key].lookup, field) == source[sheet].iloc[0][field]


@pytest.mark.parametrize("sheet", list(EXPECTED))
def test_omitted_ambiguous_candidate_is_detected_in_full_snapshot(source, sheet):
    parsed = helpers.parsed_export(source)
    record = deepcopy(source[sheet].iloc[0].to_dict())
    id_column = get_sheet_spec(sheet).id_column
    original_id = record[id_column]
    record[id_column] = original_id + 1000
    source[sheet].loc[len(source[sheet])] = record
    if sheet == "locations":
        label = deepcopy(source["location_labels"].iloc[0].to_dict())
        label.update(location_label_id=1070, location_id=record[id_column])
        source["location_labels"].loc[len(source["location_labels"])] = label
    with pytest.raises(WorkbookSelectorError, match="matched IDs") as caught:
        build(parsed, source)
    assert any(issue.sheet == sheet and issue.coordinate == "A2" for issue in caught.value.issues)
    assert str(original_id + 1000) in str(caught.value)


def test_deployment_valid_to_cannot_disambiguate_public_lookup(source):
    parsed = helpers.parsed_export(source)
    record = source["deployments"].iloc[0].to_dict()
    record.update(deployment_id=82, valid_to=helpers.START + timedelta(days=1))
    source["deployments"] = pd.DataFrame(
        [*source["deployments"].to_dict("records"), record],
        columns=source["deployments"].columns, dtype=object,
    )
    with pytest.raises(WorkbookSelectorError, match=r"matched IDs \[80, 82\]"):
        build(parsed, source)


def test_duplicate_serials_with_different_models_are_disambiguated(source):
    model = source["sensor_models"].iloc[0].to_dict()
    model.update(sensor_model_id=41, model="Other model")
    source["sensor_models"].loc[1] = model
    sensor = source["sensors"].iloc[0].to_dict()
    sensor.update(sensor_id=51, sensor_model_id=41)
    source["sensors"].loc[1] = sensor
    result = build(helpers.parsed_export(source), source)
    assert result["sensors"][50].lookup.sensor_model == "sensor_model_40"
    assert result["sensors"][51].lookup.sensor_model == "sensor_model_41"


def test_locations_with_same_initial_label_in_different_sites_are_unambiguous(source):
    source["location_labels"].at[1, "label"] = "North"
    result = build(helpers.parsed_export(source), source)
    assert result["locations"][60].lookup.site == "site_2"
    assert result["locations"][61].lookup.site == "site_3"


def test_scoped_workbook_does_not_hide_ambiguous_shared_resource(source):
    parsed = helpers.parsed_export(source, [2])
    source["sensors"].loc[1] = [51, "000001", 40, "Outside export"]
    with pytest.raises(WorkbookSelectorError, match=r"matched IDs \[50, 51\]"):
        build(parsed, source)


def test_current_location_site_missing_from_edited_workbook_gets_helper(source):
    parsed = helpers.parsed_export(source)
    parsed.frames["locations"].at[0, "site"] = "site_3"
    helpers.remove_rows(parsed, "sites", [1])
    result = build(parsed, source)
    helper = result["sites"][2]
    assert helper.helper is True
    assert helper.lookup.site_code == "north"
    assert result["locations"][60].lookup.site == helper.alias
    assert result["locations"][60].dependencies == (("sites", 2),)


def test_old_sensor_model_is_preserved_when_workbook_targets_new_declaration(source):
    parsed = helpers.parsed_export(source)
    parsed.frames["sensor_models"].at[0, "sensor_model_id"] = None
    result = build(parsed, source)
    assert result["sensor_models"][40].helper is True
    assert result["sensor_models"][40].alias != "sensor_model_40"
    assert result["sensors"][50].lookup.sensor_model == result["sensor_models"][40].alias


def test_helper_aliases_avoid_new_and_existing_workbook_aliases(source):
    parsed = helpers.parsed_export(source)
    parsed.frames["locations"].at[0, "site"] = "site_3"
    helpers.remove_rows(parsed, "sites", [1])
    row = parsed.frames["sites"].iloc[0].to_dict()
    row.update(site_id=None, site_code="new", ref="current_site_2")
    helpers.add_row(parsed, "sites", row)
    other = dict(row, site_code="other", ref="current_site_2_2")
    helpers.add_row(parsed, "sites", other)
    result = build(parsed, source)
    assert result["sites"][2].alias == "current_site_2_3"


def test_omitted_old_deployment_dependencies_are_built_recursively(source):
    parsed = helpers.parsed_export(source)
    # Keep declaration aliases but turn the old sensor/model into new candidates.
    parsed.frames["sensors"].at[0, "sensor_id"] = None
    parsed.frames["sensor_models"].at[0, "sensor_model_id"] = None
    result = build(parsed, source)
    assert result["sensors"][50].helper and result["sensor_models"][40].helper
    assert result["deployments"][80].lookup.sensor == result["sensors"][50].alias
    assert result["sensors"][50].lookup.sensor_model == result["sensor_models"][40].alias


def test_omitted_initial_label_and_timestamp_tie_use_current_history(source):
    source["location_labels"].loc[2] = [69, 60, "Earliest ID", helpers.START, None]
    parsed = helpers.parsed_export(source)
    helpers.remove_rows(parsed, "location_labels", [0, 1, 2])
    assert build(parsed, source)["locations"][60].lookup.initial_label == "Earliest ID"


def test_unlabeled_location_cannot_be_selected(source):
    parsed = helpers.parsed_export(source)
    helpers.remove_rows(parsed, "location_labels", [0, 1])
    source["location_labels"] = source["location_labels"].iloc[:0]
    with pytest.raises(WorkbookSelectorError, match="no initial label"):
        build(parsed, source)


def test_unlabeled_other_location_is_excluded_like_sql_inner_join(source):
    parsed = helpers.parsed_export(source)
    row = source["locations"].iloc[0].to_dict()
    row["location_id"] = 62
    source["locations"].loc[2] = row
    assert build(parsed, source)["locations"][60].lookup.initial_label == "North"


def test_invalid_required_hidden_identity_is_located_at_dependent_workbook_row(source):
    parsed = helpers.parsed_export(source)
    parsed.frames["locations"].at[0, "site"] = "site_3"
    helpers.remove_rows(parsed, "sites", [1])
    source["sites"].at[1, "site_code"] = " padded "
    with pytest.raises(WorkbookSelectorError) as caught:
        build(parsed, source)
    assert any(issue.sheet == "locations" and issue.coordinate == "A2"
               and "sites ID 2" in issue.message for issue in caught.value.issues)


def test_blocked_comparison_prevents_any_selector_result(source):
    parsed = helpers.parsed_export(source)
    parsed.frames["files"].at[0, "path"] = "/changed"
    with pytest.raises(WorkbookComparisonError):
        build(parsed, source)


def test_new_only_template_has_no_existing_selectors(source):
    parsed = helpers.parsed_export(source)
    parsed = replace(parsed, metadata=replace(parsed.metadata, scope="template", exported_at=None))
    for spec in RESOURCE_SHEETS:
        parsed.frames[spec.name][spec.id_column] = pd.Series([None] * len(parsed.frames[spec.name]), dtype=object)
    assert all(rows == {} for rows in build(parsed, source).values())


def test_row_and_column_order_do_not_change_generated_selectors(source):
    parsed = helpers.parsed_export(source)
    expected = dumps(build(parsed, source))
    for sheet in parsed.frames:
        parsed.frames[sheet] = parsed.frames[sheet].iloc[::-1, ::-1]
        parsed.coordinates[sheet] = parsed.coordinates[sheet].iloc[::-1, ::-1]
    assert dumps(build(parsed, source)) == expected


def test_alias_renaming_flows_through_dependency_selectors(source):
    parsed = helpers.parsed_export(source)
    parsed.frames["sites"].at[1, "ref"] = "renamed_alias"
    parsed.frames["locations"].at[0, "site"] = "renamed_alias"
    assert build(parsed, source)["locations"][60].lookup.site == "renamed_alias"


def test_timestamps_are_utc_instants_in_public_selectors(source):
    source["deployments"].at[0, "valid_from"] = helpers.START.astimezone(timezone(timedelta(hours=2)))
    lookup = build(helpers.parsed_export(source), source)["deployments"][80].lookup
    assert lookup.valid_from == helpers.START
    assert lookup.valid_from.tzinfo is timezone.utc


def test_bigint_dependency_ids_remain_exact(source):
    big = 2**63 - 1
    source["variables"].at[0, "variable_id"] = big
    source["deployments"]["variable_id"] = pd.Series([big, big], dtype=object)
    result = build(helpers.parsed_export(source), source)
    assert ("variables", big) in result["deployments"][80].dependencies
    assert result["variables"][big].database_id == big


def test_input_is_preserved_and_no_external_io_is_used(source, monkeypatch):
    matched = match_workbook(helpers.parsed_export(source), source)
    original = deepcopy(matched.rows)
    def fail(*args, **kwargs):
        pytest.fail("selector preparation attempted external IO")
    monkeypatch.setattr("builtins.open", fail)
    monkeypatch.setattr("dendroflow.configuration.metadata.connect", fail)
    monkeypatch.setattr("dendroflow.configuration.raw.connect", fail)
    result = build_workbook_selectors(matched).selectors
    result["sites"][2].lookup.site_code = "Mutated result"
    assert matched.rows == original
    assert matched.current["sites"][2]["site_code"] == "north"


def test_generated_lookups_resolve_through_existing_config_reference_and_update_apis(source, monkeypatch):
    result = build(helpers.parsed_export(source), source)
    # Use the real public resolvers, with exact expected query arguments at the
    # database boundary. This checks alias binding and public lookup composition.
    def one(sheet, field):
        def find(value):
            rows = [metadata.MetadataRow(key, row) for key, row in current[sheet].items() if row[field] == value]
            assert len(rows) == 1
            return rows[0]
        return find
    current = match_workbook(helpers.parsed_export(source), source).current
    for sheet, field, function in [
        ("sites", "site_code", "find_site"), ("location_types", "type", "find_location_type"),
        ("sensor_types", "type", "find_sensor_type"), ("variables", "variable", "find_variable"),
    ]:
        monkeypatch.setattr(metadata, function, one(sheet, field))
    def models(*, manufacturer, model):
        assert (manufacturer, model) == ("Maker", "Model")
        return (metadata.MetadataRow(40, current["sensor_models"][40]),)
    def sensors(*, serial_number, sensor_model_id):
        assert (serial_number, sensor_model_id) == ("000001", 40)
        return (metadata.MetadataRow(50, current["sensors"][50]),)
    def locations(*, site_id, initial_label):
        key = {(2, "North"): 60, (3, "South"): 61}[(site_id, initial_label)]
        return (metadata.MetadataRow(key, current["locations"][key]),)
    def deployments(*, sensor_id, location_id, variable_id, valid_from):
        assert sensor_id == 50 and variable_id == 30 and valid_from == helpers.START
        key = {60: 80, 61: 81}[location_id]
        return (metadata.MetadataRow(key, current["deployments"][key]),)
    for name, function in [("find_sensor_models", models), ("find_sensors", sensors),
                           ("find_locations", locations), ("find_deployments", deployments)]:
        monkeypatch.setattr(metadata, name, function)
    references = {sheet: {row.alias: row.lookup for row in rows.values()}
                  for sheet, rows in result.items() if sheet != "files"}
    registry = build_alias_registry(ConfigModel(references=references))
    bindings, errors = resolve_simple_reference_aliases(registry)
    assert not errors
    added, errors = resolve_sensor_model_reference_aliases(registry)
    assert not errors
    bindings += added
    for resolver in [resolve_sensor_reference_aliases,
                     resolve_location_reference_aliases, resolve_deployment_reference_aliases]:
        added, errors = resolver(registry, existing_bindings=bindings)
        assert not errors
        bindings += added
    expected = {(sheet, row.alias): row.database_id for sheet, rows in result.items() if sheet != "files"
                for row in rows.values()}
    assert {(binding.resource_type, binding.alias): binding.resource.database_id for binding in bindings} == expected
    for sheet in ("sensors", "locations", "deployments"):
        row = next(iter(result[sheet].values()))
        singular = get_sheet_spec(sheet).resource_type
        resolver = getattr(config_selectors, f"resolve_{singular}_selector")
        resolved, errors = resolver(row.lookup, source_path="test", existing_bindings=bindings)
        assert not errors and resolved.database_id == row.database_id
