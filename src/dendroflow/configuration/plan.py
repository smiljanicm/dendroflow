from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class PlanAction(str, Enum):
    CREATE = "create"
    REUSE = "reuse"
    UPDATE = "update"


class PlanErrorCode(str, Enum):
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    CONFLICT = "conflict"
    INVALID_REFERENCE = "invalid_reference"


@dataclass(frozen=True)
class ExistingRef:
    """Reference to a resource already persisted in PostgreSQL."""

    resource_type: str
    database_id: int

    def __post_init__(self) -> None:
        if not self.resource_type:
            raise ValueError("resource_type must not be empty")

        if self.database_id <= 0:
            raise ValueError("database_id must be greater than zero")


@dataclass(frozen=True)
class PlannedRef:
    """Reference to a resource that will be created by this plan."""

    resource_type: str
    plan_id: str

    def __post_init__(self) -> None:
        if not self.resource_type:
            raise ValueError("resource_type must not be empty")

        if not self.plan_id:
            raise ValueError("plan_id must not be empty")


ResourceRef = ExistingRef | PlannedRef


@dataclass(frozen=True)
class PlanBinding:
    """Bind a YAML-local alias to an exact resolved resource."""

    resource_type: str
    alias: str
    resource: ResourceRef


@dataclass(frozen=True)
class FieldChange:
    field: str
    before: object
    after: object
    identity_change: bool = False


@dataclass(frozen=True)
class ResolvedPlanItem:
    """One executable resource operation."""

    plan_id: str
    resource_type: str
    action: PlanAction
    values: object

    database_id: int | None = None
    changes: tuple[FieldChange, ...] = ()
    confirmation_required: bool = False
    source_path: str | None = None

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise ValueError("plan_id must not be empty")

        if not self.resource_type:
            raise ValueError("resource_type must not be empty")

        if self.action == PlanAction.CREATE and self.database_id is not None:
            raise ValueError(
                "CREATE plan item must not have database_id"
            )

        if (
            self.action in {PlanAction.REUSE, PlanAction.UPDATE}
            and self.database_id is None
        ):
            raise ValueError(
                f"{self.action.value.upper()} plan item "
                "must have database_id"
            )

        if self.action == PlanAction.UPDATE and not self.changes:
            raise ValueError(
                "UPDATE plan item must contain at least one change"
            )

    @property
    def requires_confirmation(self) -> bool:
        return self.confirmation_required or any(
            change.identity_change
            for change in self.changes
        )


@dataclass(frozen=True)
class PlanError:
    code: PlanErrorCode
    resource_type: str
    source_path: str
    message: str
    candidate_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class PlanWarning:
    code: str
    source_path: str
    message: str


# METADATA oriented value models


@dataclass(frozen=True)
class ResolvedSiteValues:
    site_code: str
    name: str
    description: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    parent: ResourceRef | None = None


@dataclass(frozen=True)
class ResolvedLocationTypeValues:
    type: str
    description: str | None = None


@dataclass(frozen=True)
class ResolvedSensorTypeValues:
    type: str
    description: str | None = None


@dataclass(frozen=True)
class ResolvedVariableValues:
    variable: str
    derived: bool = False
    description: str | None = None


@dataclass(frozen=True)
class ResolvedSensorModelValues:
    model: str
    manufacturer: str
    sensor_type: ResourceRef


@dataclass(frozen=True)
class ResolvedSensorValues:
    serial_number: str
    sensor_model: ResourceRef
    description: str | None = None


@dataclass(frozen=True)
class ResolvedLocationValues:
    site: ResourceRef
    location_type: ResourceRef
    latitude: float | None = None
    longitude: float | None = None
    height_above_ground: float | None = None
    azimuth: float | None = None


@dataclass(frozen=True)
class ResolvedLocationLabelValues:
    location: ResourceRef
    label: str
    valid_from: datetime
    valid_to: datetime | None = None


@dataclass(frozen=True)
class ResolvedDeploymentValues:
    sensor: ResourceRef
    location: ResourceRef
    variable: ResourceRef
    valid_from: datetime
    valid_to: datetime | None = None


# RAW oriented value models


@dataclass(frozen=True)
class ResolvedFileValues:
    filepath: str
    timestamp_timezone: str
    timestamp_format: str
    reader_config: Mapping[str, object]


@dataclass(frozen=True)
class ResolvedInterfaceValues:
    file: ResourceRef
    deployment: ResourceRef
    values_column: str
    timestamp_column: str
    unit: str


# Final plan model


@dataclass(frozen=True)
class ResolvedPlan:
    metadata_items: tuple[ResolvedPlanItem, ...] = ()
    raw_items: tuple[ResolvedPlanItem, ...] = ()
    bindings: tuple[PlanBinding, ...] = ()
    errors: tuple[PlanError, ...] = ()
    warnings: tuple[PlanWarning, ...] = ()

    @property
    def items(self) -> tuple[ResolvedPlanItem, ...]:
        return self.metadata_items + self.raw_items

    @property
    def can_apply(self) -> bool:
        return not self.errors

    @property
    def requires_confirmation(self) -> bool:
        return any(
            item.requires_confirmation
            for item in self.items
        )

    def count(self, action: PlanAction) -> int:
        return sum(
            item.action == action
            for item in self.items
        )


