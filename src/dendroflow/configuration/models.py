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


class ConfigModel(ConfigBaseModel):
    sites: list[SiteConfig] = Field(default_factory=list)
    location_types: list[LocationTypeConfig] = Field(
        default_factory=list
    )
    sensor_types: list[SensorTypeConfig] = Field(
        default_factory=list
    )
    variables: list[VariableConfig] = Field(
        default_factory=list
    )