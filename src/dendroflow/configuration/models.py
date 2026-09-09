from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConfigBaseModel(BaseModel):
    """Base model for human-facing DendroFlow configuration."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class SiteConfig(ConfigBaseModel):
    site_code: str = Field(min_length=1)
    name: str = Field(min_length=1)

    ref: str | None = None
    description: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    parent: str | None = None

    @model_validator(mode="after")
    def validate_coordinates(self) -> "SiteConfig":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError(
                "latitude and longitude must either both be set "
                "or both be omitted"
            )

        if self.latitude is not None and not -90 <= self.latitude <= 90:
            raise ValueError(
                "latitude must be between -90 and 90"
            )

        if self.longitude is not None and not -180 <= self.longitude <= 180:
            raise ValueError(
                "longitude must be between -180 and 180"
            )

        return self


class LocationTypeConfig(ConfigBaseModel):
    type: str = Field(min_length=1)

    ref: str | None = None
    description: str | None = None


class SensorTypeConfig(ConfigBaseModel):
    type: str = Field(min_length=1)

    ref: str | None = None
    description: str | None = None


class VariableConfig(ConfigBaseModel):
    variable: str = Field(min_length=1)

    ref: str | None = None
    derived: bool = False
    description: str | None = None


class SensorModelConfig(ConfigBaseModel):
    model: str = Field(min_length=1)
    manufacturer: str = Field(min_length=1)
    sensor_type: str = Field(min_length=1)

    ref: str | None = None


class SensorConfig(ConfigBaseModel):
    serial_number: str = Field(min_length=1)
    sensor_model: str = Field(min_length=1)

    ref: str | None = None
    description: str | None = None


class InitialLocationLabelConfig(ConfigBaseModel):
    label: str = Field(min_length=1)
    valid_from: datetime
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def validate_validity(self) -> "InitialLocationLabelConfig":
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        return self


class LocationConfig(ConfigBaseModel):
    site: str = Field(min_length=1)
    location_type: str = Field(min_length=1)
    initial_label: InitialLocationLabelConfig

    ref: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    height_above_ground: float | None = None
    azimuth: float | None = None

    @model_validator(mode="after")
    def validate_coordinates(self) -> "LocationConfig":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError(
                "latitude and longitude must either both be set "
                "or both be omitted"
            )

        if self.latitude is not None and not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")

        if self.longitude is not None and not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")

        if self.azimuth is not None and not 0 <= self.azimuth < 360:
            raise ValueError("azimuth must be greater than or equal to 0 and less than 360")

        return self


class LocationLabelConfig(ConfigBaseModel):
    location: str = Field(min_length=1)
    label: str = Field(min_length=1)
    valid_from: datetime
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def validate_validity(self) -> "LocationLabelConfig":
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        return self


class DeploymentConfig(ConfigBaseModel):
    sensor: str = Field(min_length=1)
    location: str = Field(min_length=1)
    variable: str = Field(min_length=1)
    valid_from: datetime

    ref: str | None = None
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def validate_validity(self) -> "DeploymentConfig":
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        return self


class ConfigModel(ConfigBaseModel):
    sites: list[SiteConfig] = Field(default_factory=list)
    location_types: list[LocationTypeConfig] = Field(default_factory=list)
    sensor_types: list[SensorTypeConfig] = Field(default_factory=list)
    variables: list[VariableConfig] = Field(default_factory=list)

    sensor_models: list[SensorModelConfig] = Field(default_factory=list)
    sensors: list[SensorConfig] = Field(default_factory=list)
    locations: list[LocationConfig] = Field(default_factory=list)
    location_labels: list[LocationLabelConfig] = Field(default_factory=list)
    deployments: list[DeploymentConfig] = Field(default_factory=list)
