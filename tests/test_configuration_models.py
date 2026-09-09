import pytest
from pydantic import ValidationError

from dendroflow.configuration import (
    ConfigModel,
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
