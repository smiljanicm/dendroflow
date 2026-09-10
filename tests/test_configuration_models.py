import pytest
from pydantic import ValidationError

from dendroflow.configuration import (
    ConfigModel,
    DeploymentConfig,
    DeploymentLookupConfig,
    DeploymentUpdateConfig,
    FileConfig,
    InitialLocationLabelConfig,
    InterfaceConfig,
    LocationConfig,
    ReaderConfig,
    SensorConfig,
    SensorLookupConfig,
    SensorModelConfig,
    SensorUpdateConfig,
    SiteConfig,
    TimestampConfig,
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


def test_file_config_accepts_sandhagen_structure():
    file = FileConfig(
        ref="sandhagen_water_table",
        path="tests/data/Sandhagen_Rewetted_WaterTbl.dat",
        timestamp={
            "timezone": "Etc/GMT-1",
            "format": "%Y-%m-%d %H:%M:%S",
        },
        reader={
            "type": "csv",
            "options": {
                "skiprows": [0, 2, 3],
                "delimiter": ",",
            },
        },
        interfaces=[
            {
                "deployment": "water_level_main",
                "timestamp_column": "TIMESTAMP",
                "values_column": "Lvl_cm_Avg",
                "unit": "cm",
            }
        ],
    )

    assert file.timestamp.timezone == "Etc/GMT-1"
    assert file.reader.type == "csv"
    assert file.reader.options["skiprows"] == [0, 2, 3]
    assert file.interfaces[0].deployment == "water_level_main"


def test_timestamp_config_rejects_unknown_timezone():
    with pytest.raises(
        ValidationError,
        match="unknown timezone",
    ):
        TimestampConfig(
            timezone="Not/A/Timezone",
            format="%Y-%m-%d %H:%M:%S",
        )


def test_reader_config_rejects_unsupported_reader():
    with pytest.raises(ValidationError):
        ReaderConfig(
            type="parquet",
        )


def test_file_config_requires_interface():
    with pytest.raises(ValidationError):
        FileConfig(
            path="data.csv",
            timestamp={
                "timezone": "UTC",
                "format": "%Y-%m-%d %H:%M:%S",
            },
            reader={
                "type": "csv",
            },
            interfaces=[],
        )


def test_interface_config_rejects_empty_values_column():
    with pytest.raises(ValidationError):
        InterfaceConfig(
            deployment="water_level_main",
            timestamp_column="TIMESTAMP",
            values_column="",
            unit="cm",
        )


def test_config_model_accepts_files():
    config = ConfigModel(
        files=[
            {
                "path": "data.csv",
                "timestamp": {
                    "timezone": "UTC",
                    "format": "%Y-%m-%d %H:%M:%S",
                },
                "reader": {
                    "type": "csv",
                },
                "interfaces": [
                    {
                        "deployment": "water_level_main",
                        "timestamp_column": "TIMESTAMP",
                        "values_column": "value",
                        "unit": "cm",
                    }
                ],
            }
        ]
    )

    assert len(config.files) == 1


def test_references_accept_minimal_deployment_lookup():
    config = ConfigModel(
        references={
            "deployments": {
                "water_level_main": {
                    "sensor": "123456",
                }
            }
        }
    )

    lookup = config.references.deployments["water_level_main"]
    assert lookup.sensor == "123456"
    assert lookup.variable is None


def test_lookup_rejects_empty_selector():
    with pytest.raises(
        ValidationError,
        match="lookup must contain at least one identifying field",
    ):
        DeploymentLookupConfig()


def test_sensor_model_reference_accepts_natural_identity():
    config = ConfigModel(
        references={
            "sensor_models": {
                "cs451": {
                    "manufacturer": "Campbell Scientific",
                    "model": "CS451",
                }
            }
        }
    )

    lookup = config.references.sensor_models["cs451"]
    assert lookup.model == "CS451"


def test_sensor_update_accepts_serial_number_change():
    update = SensorUpdateConfig(
        update={
            "serial_number": "OLD123",
        },
        set={
            "serial_number": "NEW123",
        },
    )

    assert update.update.serial_number == "OLD123"
    assert update.set.serial_number == "NEW123"


def test_update_rejects_empty_set():
    with pytest.raises(
        ValidationError,
        match="set must contain at least one field",
    ):
        SensorUpdateConfig(
            update={
                "serial_number": "123456",
            },
            set={},
        )


def test_deployment_update_accepts_valid_to():
    update = DeploymentUpdateConfig(
        update={
            "sensor": "123456",
            "variable": "water_level",
        },
        set={
            "valid_to": "2026-09-01T00:00:00Z",
        },
    )

    assert update.set.valid_to is not None


def test_deployment_update_can_clear_valid_to():
    update = DeploymentUpdateConfig(
        update={
            "sensor": "123456",
        },
        set={
            "valid_to": None,
        },
    )

    assert "valid_to" in update.set.model_fields_set
    assert update.set.valid_to is None


def test_config_defaults_references_and_updates_to_empty():
    config = ConfigModel()

    assert config.references.deployments == {}
    assert config.updates.sensors == []


def test_sensor_lookup_accepts_sensor_model():
    lookup = SensorLookupConfig(
        serial_number="123456",
        sensor_model="cs451",
    )

    assert lookup.serial_number == "123456"
    assert lookup.sensor_model == "cs451"

