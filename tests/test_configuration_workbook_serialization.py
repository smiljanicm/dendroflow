from datetime import timedelta

import pytest

from dendroflow.configuration.workbook.configuration import generate_configuration
from dendroflow.configuration.workbook.matching import match_workbook
from dendroflow.configuration.workbook.serialization import serialize_configuration

from . import test_configuration_workbook_validation as helpers


@pytest.fixture
def source():
    return helpers.source.__wrapped__()


def serialize(parsed, source):
    generated = generate_configuration(match_workbook(parsed, source))
    return serialize_configuration(generated.config)


def test_unchanged_workbook_serializes_to_valid_reference_only_yaml(source):
    result = serialize(helpers.parsed_export(source), source)

    assert result.yaml_text.startswith("sites: []\n")
    assert result.config.sites == []
    assert set(result.config.references.sites) == {"site_1", "site_2", "site_3"}


def test_explicit_nullable_update_clear_survives_yaml_round_trip(source):
    source["sites"].at[1, "description"] = "Existing description"
    parsed = helpers.parsed_export(source)
    parsed.frames["sites"].at[1, "description"] = None

    result = serialize(parsed, source)
    change = result.config.updates.sites[0].set

    assert "description: null" in result.yaml_text
    assert "description" in change.model_fields_set
    assert change.description is None


def test_nested_resources_timestamps_and_text_survive_deterministically(source):
    parsed = helpers.parsed_export(source)
    location = parsed.frames["locations"].iloc[0].to_dict()
    location.update(location_id=None, ref="new_location")
    helpers.add_row(parsed, "locations", location)
    label = parsed.frames["location_labels"].iloc[0].to_dict()
    label.update(
        location_label_id=None,
        ref="new_initial",
        location="new_location",
        label="TRUE",
        valid_from=helpers.START + timedelta(days=5),
        is_initial=True,
    )
    helpers.add_row(parsed, "location_labels", label)

    first = serialize(parsed, source)
    second = serialize(parsed, source)

    assert first.yaml_text == second.yaml_text
    assert first.config.locations[0].initial_label.label == "TRUE"
    assert first.config.locations[0].initial_label.valid_from == label["valid_from"]
