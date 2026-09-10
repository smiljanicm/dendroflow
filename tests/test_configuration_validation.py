import pytest

from dendroflow.configuration import (
    ConfigModel,
    ConfigValidationError,
    collect_config_issues,
    validate_config,
)


def test_validate_config_accepts_consistent_config():
    config = ConfigModel(
        sites=[
            {
                "ref": "sandhagen",
                "site_code": "sandhagen_rewetted",
                "name": "Sandhagen Rewetted",
            }
        ],
        variables=[
            {
                "ref": "water_level",
                "variable": "water_level",
            }
        ],
    )

    validate_config(config)


def test_validate_config_rejects_duplicate_declaration_ref():
    config = ConfigModel(
        variables=[
            {
                "ref": "water_level",
                "variable": "water_level",
            },
            {
                "ref": "water_level",
                "variable": "water_temperature",
            },
        ]
    )

    with pytest.raises(
        ConfigValidationError,
        match="duplicate variables ref",
    ):
        validate_config(config)


def test_validate_config_rejects_declaration_reference_collision():
    config = ConfigModel(
        sensors=[
            {
                "ref": "sensor_01",
                "serial_number": "123456",
                "sensor_model": "cs451",
            }
        ],
        references={
            "sensors": {
                "sensor_01": {
                    "serial_number": "987654",
                }
            }
        },
    )

    with pytest.raises(
        ConfigValidationError,
        match="also used by a declaration ref",
    ):
        validate_config(config)


def test_validate_config_rejects_duplicate_site_identity():
    config = ConfigModel(
        sites=[
            {
                "site_code": "sandhagen",
                "name": "Sandhagen",
            },
            {
                "site_code": "sandhagen",
                "name": "Different name",
            },
        ]
    )

    with pytest.raises(
        ConfigValidationError,
        match="duplicate natural identity",
    ):
        validate_config(config)


def test_validate_config_rejects_duplicate_sensor_model_identity():
    config = ConfigModel(
        sensor_models=[
            {
                "manufacturer": "Campbell Scientific",
                "model": "CS451",
                "sensor_type": "water_level",
            },
            {
                "manufacturer": "Campbell Scientific",
                "model": "CS451",
                "sensor_type": "other",
            },
        ]
    )

    with pytest.raises(
        ConfigValidationError,
        match="duplicate natural identity",
    ):
        validate_config(config)


def test_validation_collects_multiple_issues():
    config = ConfigModel(
        variables=[
            {
                "ref": "water",
                "variable": "water_level",
            },
            {
                "ref": "water",
                "variable": "water_level",
            },
        ],
        sites=[
            {
                "site_code": "sandhagen",
                "name": "Sandhagen",
            },
            {
                "site_code": "sandhagen",
                "name": "Duplicate",
            },
        ],
    )

    issues = collect_config_issues(config)

    assert len(issues) == 3


def test_validation_rejects_unknown_sensor_model_reference():
    config = ConfigModel(
        sensors=[
            {
                "serial_number": "123456",
                "sensor_model": "cs451",
            }
        ]
    )

    with pytest.raises(
        ConfigValidationError,
        match="unknown sensor_models reference: cs451",
    ):
        validate_config(config)


def test_validation_accepts_declared_relationship_reference():
    config = ConfigModel(
        sensor_types=[
            {
                "ref": "water_level",
                "type": "water_level",
            }
        ],
        sensor_models=[
            {
                "ref": "cs451",
                "manufacturer": "Campbell Scientific",
                "model": "CS451",
                "sensor_type": "water_level",
            }
        ],
        sensors=[
            {
                "serial_number": "123456",
                "sensor_model": "cs451",
            }
        ],
    )

    validate_config(config)


def test_validation_accepts_existing_resource_alias():
    config = ConfigModel(
        references={
            "sensor_models": {
                "cs451": {
                    "manufacturer": "Campbell Scientific",
                    "model": "CS451",
                }
            }
        },
        sensors=[
            {
                "serial_number": "123456",
                "sensor_model": "cs451",
            }
        ],
    )

    validate_config(config)


def test_validation_reports_unknown_location_dependencies():
    config = ConfigModel(
        locations=[
            {
                "site": "sandhagen",
                "location_type": "well",
                "initial_label": {
                    "label": "Rewetted well",
                    "valid_from": "2025-04-01T00:00:00Z",
                },
            }
        ]
    )

    issues = collect_config_issues(config)

    assert len(issues) == 2
    assert issues[0].path == "locations[0].site"
    assert issues[1].path == "locations[0].location_type"


def test_validation_reports_unknown_deployment_dependencies():
    config = ConfigModel(
        deployments=[
            {
                "sensor": "sensor_01",
                "location": "well_01",
                "variable": "water_level",
                "valid_from": "2025-04-01T00:00:00Z",
            }
        ]
    )

    issues = collect_config_issues(config)

    assert len(issues) == 3


def test_validation_rejects_unknown_interface_deployment():
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

    with pytest.raises(
        ConfigValidationError,
        match="unknown deployments reference: water_level_main",
    ):
        validate_config(config)


def test_validation_does_not_resolve_reference_lookup_fields_locally():
    config = ConfigModel(
        references={
            "deployments": {
                "water_level_main": {
                    "sensor": "123456",
                }
            }
        }
    )

    validate_config(config)

