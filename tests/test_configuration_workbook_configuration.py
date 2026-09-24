from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pandas as pd
import pytest

from dendroflow.configuration.validation import validate_config
from dendroflow.configuration.workbook.comparison import ComparisonStatus
from dendroflow.configuration.workbook.configuration import (
    WorkbookConfigurationError,
    generate_configuration,
)
from dendroflow.configuration.workbook.matching import match_workbook
from dendroflow.configuration.workbook.schema import RESOURCE_SHEETS

from . import test_configuration_workbook_validation as helpers


@pytest.fixture
def source():
    return helpers.source.__wrapped__()


def generated(parsed, source):
    return generate_configuration(match_workbook(parsed, source))


def test_unchanged_workbook_generates_valid_reference_only_config(source):
    result = generated(helpers.parsed_export(source), source)
    validate_config(result.config)
    assert not result.config.sites
    assert not result.config.files
    assert all(not getattr(result.config.updates, field)
               for field in type(result.config.updates).model_fields)
    assert set(result.config.references.sites) == {"site_1", "site_2", "site_3"}
    assert set(result.config.references.files) == set()
    assert result.comparison.issues == ()


def test_supported_site_rename_becomes_update_using_old_selector(source):
    parsed = helpers.parsed_export(source)
    parsed.frames["sites"].at[1, "site_code"] = "north_renamed"
    config = generated(parsed, source).config
    assert config.sites == []
    assert len(config.updates.sites) == 1
    update = config.updates.sites[0]
    assert update.update.site_code == "north"
    assert update.set.model_dump(exclude_unset=True) == {"site_code": "north_renamed"}
    validate_config(config)


def test_supported_relationship_update_uses_verified_target_alias(source):
    parsed = helpers.parsed_export(source)
    parsed.frames["deployments"].at[0, "sensor"] = "sensor_50"
    parsed.frames["deployments"].at[0, "valid_to"] = helpers.START + timedelta(days=1)
    source["deployments"].at[0, "valid_to"] = None
    config = generated(parsed, source).config
    update = config.updates.deployments[0]
    assert update.update.sensor == "sensor_50"
    assert update.set.model_dump(exclude_unset=True) == {
        "valid_to": helpers.START + timedelta(days=1),
    }


def test_nullable_field_clear_is_preserved_as_explicit_null(source):
    source["sites"].at[1, "description"] = "Clear this"
    parsed = helpers.parsed_export(source)
    parsed.frames["sites"].at[1, "description"] = None
    update = generated(parsed, source).config.updates.sites[0]
    assert "description" in update.set.model_fields_set
    assert update.set.description is None


def test_new_simple_declaration_and_supported_update_can_coexist(source):
    parsed = helpers.parsed_export(source)
    new_site = parsed.frames["sites"].iloc[1].to_dict()
    new_site.update(site_id=None, ref="new_site", site_code="new", name="New Site", parent="site_1")
    helpers.add_row(parsed, "sites", new_site)
    parsed.frames["sites"].at[1, "name"] = "Renamed North"
    result = generated(parsed, source)
    validate_config(result.config)
    assert [(site.ref, site.site_code, site.parent) for site in result.config.sites] == [
        ("new_site", "new", "site_1"),
    ]
    assert result.config.updates.sites[0].update.site_code == "north"
    assert result.config.updates.sites[0].set.name == "Renamed North"


def test_new_location_nests_initial_label_and_keeps_later_label_top_level(source):
    parsed = helpers.parsed_export(source)
    location = parsed.frames["locations"].iloc[0].to_dict()
    location.update(location_id=None, ref="new_location", site="site_2")
    helpers.add_row(parsed, "locations", location)
    label = parsed.frames["location_labels"].iloc[0].to_dict()
    label.update(location_label_id=None, ref="new_initial", location="new_location",
                 label="New initial", valid_from=helpers.START + timedelta(days=5), is_initial=True)
    helpers.add_row(parsed, "location_labels", label)
    later = dict(label, ref="new_later", label="Later", valid_from=helpers.START + timedelta(days=10),
                 is_initial=False)
    helpers.add_row(parsed, "location_labels", later)
    generated_result = generated(parsed, source)
    result = generated_result.config
    validate_config(result)
    assert len(result.locations) == 1
    assert result.locations[0].ref == "new_location"
    assert result.locations[0].initial_label.label == "New initial"
    assert [(item.label, item.location) for item in result.location_labels] == [
        ("Later", "new_location"),
    ]
    assert generated_result.comparison.rows["locations"][-1].status == ComparisonStatus.NEW


def test_new_dependent_declarations_resolve_aliases_without_ids(source):
    parsed = helpers.parsed_export(source)
    model = parsed.frames["sensor_models"].iloc[0].to_dict()
    model.update(sensor_model_id=None, ref="new_model", model="New Model")
    helpers.add_row(parsed, "sensor_models", model)
    sensor = parsed.frames["sensors"].iloc[0].to_dict()
    sensor.update(sensor_id=None, ref="new_sensor", serial_number="000002", sensor_model="new_model")
    helpers.add_row(parsed, "sensors", sensor)
    deployment = parsed.frames["deployments"].iloc[0].to_dict()
    deployment.update(deployment_id=None, ref="new_deployment", sensor="new_sensor",
                      valid_from=helpers.START + timedelta(days=2))
    helpers.add_row(parsed, "deployments", deployment)
    config = generated(parsed, source).config
    validate_config(config)
    assert config.sensor_models[0].sensor_type == "sensor_type_20"
    assert config.sensors[0].sensor_model == "new_model"
    assert config.deployments[0].sensor == "new_sensor"


def test_existing_file_settings_wrap_new_interface_and_resolve_current_file(source):
    parsed = helpers.parsed_export(source)
    interface = parsed.frames["interfaces"].iloc[0].to_dict()
    interface.update(interface_id=None, ref="new_interface", values_column="new_column")
    helpers.add_row(parsed, "interfaces", interface)
    config = generated(parsed, source).config
    validate_config(config)
    assert len(config.files) == 1
    assert config.files[0].path == "/data/shared.csv"
    assert config.files[0].ref == "file_90"
    assert len(config.files[0].interfaces) == 1
    assert config.files[0].interfaces[0].deployment == "deployment_80"


def test_new_file_and_interface_are_nested_together(source):
    parsed = helpers.parsed_export(source)
    file = parsed.frames["files"].iloc[0].to_dict()
    file.update(file_id=None, ref="new_file", path="/data/new.csv", reader_options={"delimiter": ";"})
    helpers.add_row(parsed, "files", file)
    interface = parsed.frames["interfaces"].iloc[0].to_dict()
    interface.update(interface_id=None, ref="new_interface", file="new_file", values_column="new_column")
    helpers.add_row(parsed, "interfaces", interface)
    config = generated(parsed, source).config
    validate_config(config)
    assert len(config.files) == 1 and config.files[0].ref == "new_file"
    assert config.files[0].path == "/data/new.csv"
    assert config.files[0].reader.options == {"delimiter": ";"}
    assert config.files[0].interfaces[0].values_column == "new_column"


def test_multiple_new_interfaces_group_under_one_file(source):
    parsed = helpers.parsed_export(source)
    for n in range(2):
        interface = parsed.frames["interfaces"].iloc[0].to_dict()
        interface.update(interface_id=None, ref=f"added_{n}", values_column=f"added_column_{n}")
        helpers.add_row(parsed, "interfaces", interface)
    config = generated(parsed, source).config
    assert len(config.files) == 1
    assert [item.values_column for item in config.files[0].interfaces] == ["added_column_0", "added_column_1"]


def test_scoped_export_includes_read_only_dependencies_for_new_records(source):
    parsed = helpers.parsed_export(source, [2])
    parsed.frames["locations"].at[0, "latitude"] = 54.0
    config = generated(parsed, source).config
    assert "site_1" in config.references.sites  # required ancestor
    assert "location_type_10" in config.references.location_types
    assert "sensor_50" in config.references.sensors
    assert "variable_30" in config.references.variables
    assert config.updates.locations[0].update.initial_label == "North"


def test_template_becomes_valid_declarations_with_no_references(source):
    parsed = helpers.parsed_export(source)
    parsed = replace(parsed, metadata=replace(parsed.metadata, scope="template", exported_at=None))
    for spec in RESOURCE_SHEETS:
        parsed.frames[spec.name][spec.id_column] = pd.Series([None] * len(parsed.frames[spec.name]), dtype=object)
    result = generated(parsed, source)
    validate_config(result.config)
    assert not result.config.references.sites
    assert len(result.config.sites) == 3
    assert len(result.config.locations) == 2
    assert len(result.config.deployments) == 2
    assert len(result.config.files) == 1


def test_empty_template_becomes_empty_valid_config(source):
    parsed = helpers.parsed_export(source)
    parsed = replace(parsed, metadata=replace(parsed.metadata, scope="template", exported_at=None))
    for spec in RESOURCE_SHEETS:
        parsed.frames[spec.name][spec.id_column] = pd.Series([None] * len(parsed.frames[spec.name]), dtype=object)
        helpers.remove_rows(parsed, spec.name, list(parsed.frames[spec.name].index))
    config = generated(parsed, source).config
    validate_config(config)
    assert not config.sites and not config.references.sites and not config.updates.sites


def test_blocked_workbook_never_generates_partial_config(source):
    parsed = helpers.parsed_export(source)
    parsed.frames["sites"].at[1, "parent"] = None
    with pytest.raises(Exception, match="not supported"):
        generated(parsed, source)


def test_semantically_invalid_generated_config_returns_validation_issues(source):
    parsed = helpers.parsed_export(source)
    site = parsed.frames["sites"].iloc[1].to_dict()
    site.update(site_id=None, ref="duplicate_one", site_code="duplicate", name="Duplicate One")
    helpers.add_row(parsed, "sites", site)
    second = dict(site, ref="duplicate_two", name="Duplicate Two")
    helpers.add_row(parsed, "sites", second)
    with pytest.raises(WorkbookConfigurationError) as caught:
        generated(parsed, source)
    assert caught.value.issues
    assert any("duplicate" in issue.message for issue in caught.value.issues)


def test_new_and_updated_aliases_are_type_scoped_and_preserve_leading_zeros(source):
    parsed = helpers.parsed_export(source)
    new_sensor = parsed.frames["sensors"].iloc[0].to_dict()
    new_sensor.update(sensor_id=None, ref="sensor_999", serial_number="00000042")
    helpers.add_row(parsed, "sensors", new_sensor)
    parsed.frames["variables"].at[0, "variable"] = "renamed"
    config = generated(parsed, source).config
    assert config.sensors[0].serial_number == "00000042"
    assert config.updates.variables[0].update.variable == "level"
    assert config.updates.variables[0].set.variable == "renamed"


def test_generation_is_deterministic_and_does_not_mutate_inputs(source):
    parsed = helpers.parsed_export(source)
    new = parsed.frames["sites"].iloc[0].to_dict()
    new.update(site_id=None, ref="new", site_code="new", name="New")
    helpers.add_row(parsed, "sites", new)
    matched = match_workbook(parsed, source)
    before = deepcopy(matched.rows)
    first = generate_configuration(matched).config.model_dump(mode="python")
    second = generate_configuration(matched).config.model_dump(mode="python")
    assert first == second
    assert matched.rows == before


def test_validation_issue_mapping_preserves_update_field_cell_coordinate(source):
    parsed = helpers.parsed_export(source)
    site = parsed.frames["sites"].iloc[0].to_dict()
    site.update(site_id=None, ref="invalid_site", site_code="invalid", name="Invalid",
                latitude=50.0, longitude=None)
    helpers.add_row(parsed, "sites", site)
    with pytest.raises(WorkbookConfigurationError) as caught:
        generated(parsed, source)
    assert any(issue.sheet == "sites" and issue.coordinate == "A103" for issue in caught.value.issues)
