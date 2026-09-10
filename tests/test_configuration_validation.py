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

