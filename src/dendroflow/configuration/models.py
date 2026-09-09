from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


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


class TimestampConfig(ConfigBaseModel):
    timezone: str = Field(min_length=1)
    format: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_timezone(self) -> "TimestampConfig":
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f"unknown timezone: {self.timezone}"
            ) from exc

        return self


class ReaderConfig(ConfigBaseModel):
    type: Literal["csv"]
    options: dict[str, object] = Field(default_factory=dict)


class InterfaceConfig(ConfigBaseModel):
    deployment: str = Field(min_length=1)
    timestamp_column: str = Field(min_length=1)
    values_column: str = Field(min_length=1)
    unit: str = Field(min_length=1)


class FileConfig(ConfigBaseModel):
    path: str = Field(min_length=1)
    timestamp: TimestampConfig
    reader: ReaderConfig
    interfaces: list[InterfaceConfig] = Field(min_length=1)

    ref: str | None = None


ReferenceAlias = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class LookupConfig(ConfigBaseModel):
    """Base model for selectors of existing resources."""

    @model_validator(mode="after")
    def validate_lookup(self) -> "LookupConfig":
        values = self.model_dump(exclude_none=True)

        if not values:
            raise ValueError(
                "lookup must contain at least one identifying field"
            )

        return self


class SiteLookupConfig(LookupConfig):
    site_code: str | None = None


class LocationTypeLookupConfig(LookupConfig):
    type: str | None = None


class SensorTypeLookupConfig(LookupConfig):
    type: str | None = None


class VariableLookupConfig(LookupConfig):
    variable: str | None = None


class SensorModelLookupConfig(LookupConfig):
    manufacturer: str | None = None
    model: str | None = None


class SensorLookupConfig(LookupConfig):
    serial_number: str | None = None


class LocationLookupConfig(LookupConfig):
    site: str | None = None
    initial_label: str | None = None


class DeploymentLookupConfig(LookupConfig):
    sensor: str | None = None
    location: str | None = None
    variable: str | None = None
    valid_from: datetime | None = None


class FileLookupConfig(LookupConfig):
    path: str | None = None


class ReferencesConfig(ConfigBaseModel):
    sites: dict[ReferenceAlias, SiteLookupConfig] = Field(
        default_factory=dict
    )
    location_types: dict[
        ReferenceAlias, LocationTypeLookupConfig
    ] = Field(default_factory=dict)
    sensor_types: dict[
        ReferenceAlias, SensorTypeLookupConfig
    ] = Field(default_factory=dict)
    variables: dict[ReferenceAlias, VariableLookupConfig] = Field(
        default_factory=dict
    )
    sensor_models: dict[
        ReferenceAlias, SensorModelLookupConfig
    ] = Field(default_factory=dict)
    sensors: dict[ReferenceAlias, SensorLookupConfig] = Field(
        default_factory=dict
    )
    locations: dict[ReferenceAlias, LocationLookupConfig] = Field(
        default_factory=dict
    )
    deployments: dict[
        ReferenceAlias, DeploymentLookupConfig
    ] = Field(default_factory=dict)
    files: dict[ReferenceAlias, FileLookupConfig] = Field(
        default_factory=dict
    )


class UpdateFieldsConfig(ConfigBaseModel):
    """Base model for fields explicitly requested to change."""

    @model_validator(mode="after")
    def validate_set(self) -> "UpdateFieldsConfig":
        if not self.model_fields_set:
            raise ValueError(
                "set must contain at least one field"
            )

        return self


class SensorUpdateFieldsConfig(UpdateFieldsConfig):
    serial_number: str | None = Field(
        default=None,
        min_length=1,
    )
    description: str | None = None


class SensorUpdateConfig(ConfigBaseModel):
    update: SensorLookupConfig
    set: SensorUpdateFieldsConfig


class DeploymentUpdateFieldsConfig(UpdateFieldsConfig):
    sensor: str | None = Field(default=None, min_length=1)
    location: str | None = Field(default=None, min_length=1)
    variable: str | None = Field(default=None, min_length=1)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class DeploymentUpdateConfig(ConfigBaseModel):
    update: DeploymentLookupConfig
    set: DeploymentUpdateFieldsConfig


class UpdatesConfig(ConfigBaseModel):
    sensors: list[SensorUpdateConfig] = Field(default_factory=list)
    deployments: list[DeploymentUpdateConfig] = Field(
        default_factory=list
    )


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

    files: list[FileConfig] = Field(default_factory=list)

    references: ReferencesConfig = Field(
        default_factory=ReferencesConfig
    )
    updates: UpdatesConfig = Field(
        default_factory=UpdatesConfig
    )

