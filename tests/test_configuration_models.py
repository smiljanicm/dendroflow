import pytest
from pydantic import ValidationError

from dendroflow.configuration import (
    ConfigModel,
    DeploymentConfig,
    InitialLocationLabelConfig,
    LocationConfig,
    SensorConfig,
    SensorModelConfig,
    SiteConfig,
    VariableConfig,
)


def test_config_model_defaults_to_empty_sections():
    config = ConfigModel()

    assert config.sites == []
    assert config.location_types == []
    assert config.sensor_types == []
    assert config.variables == []


def test_site_config_accepts_coordinate_pair():
    site = SiteConfig(
        site_code="sandhagen_rewetted",
        name="Sandhagen Rewetted",
        latitude=54.0,
        longitude=13.0,
    )

    assert site.site_code == "sandhagen_rewetted"
    assert site.latitude == 54.0
    assert site.longitude == 13.0


def test_site_config_rejects_partial_coordinate_pair():
    with pytest.raises(
        ValidationError,
        match="latitude and longitude must either both be set",
    ):
        SiteConfig(
            site_code="sandhagen_rewetted",
            name="Sandhagen Rewetted",
            latitude=54.0,
        )


def test_site_config_rejects_invalid_latitude():
    with pytest.raises(
        ValidationError,
        match="latitude must be between -90 and 90",
    ):
        SiteConfig(
            site_code="sandhagen_rewetted",
            name="Sandhagen Rewetted",
            latitude=100.0,
            longitude=13.0,
        )


def test_variable_defaults_to_measured():
    variable = VariableConfig(
        variable="water_level",
    )

    assert variable.derived is False


def test_config_model_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ConfigModel(
            unknown_section=[],
        )


def test_sensor_model_config():
    model = SensorModelConfig(
        manufacturer="Campbell Scientific",
        model="CS451",
        sensor_type="water_level",
    )

    assert model.model == "CS451"
    assert model.sensor_type == "water_level"


def test_sensor_config_keeps_sensor_model_reference_unresolved():
    sensor = SensorConfig(
        serial_number="123456",
        sensor_model="cs451",
    )

    assert sensor.sensor_model == "cs451"


def test_location_config_accepts_initial_label():
    location = LocationConfig(
        site="sandhagen",
        location_type="well",
        initial_label={
            "label": "Rewetted well",
            "valid_from": "2025-04-01T00:00:00Z",
        },
    )

    assert location.initial_label.label == "Rewetted well"


def test_initial_location_label_rejects_invalid_validity():
    with pytest.raises(
        ValidationError,
        match="valid_to must be later than valid_from",
    ):
        InitialLocationLabelConfig(
            label="Rewetted well",
            valid_from="2025-04-02T00:00:00Z",
            valid_to="2025-04-01T00:00:00Z",
        )


def test_deployment_rejects_invalid_validity():
    with pytest.raises(
        ValidationError,
        match="valid_to must be later than valid_from",
    ):
        DeploymentConfig(
            sensor="sensor_01",
            location="rewetted_well",
            variable="water_level",
            valid_from="2025-04-02T00:00:00Z",
            valid_to="2025-04-01T00:00:00Z",
        )