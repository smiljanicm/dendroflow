from dataclasses import dataclass
from enum import Enum

from dendroflow.configuration.plan import (
    PlanAction,
)


class ApplyErrorCode(str, Enum):
    PLAN_NOT_APPLICABLE = "plan_not_applicable"
    CONFIRMATION_REQUIRED = "confirmation_required"
    UNRESOLVED_PLANNED_REF = "unresolved_planned_ref"
    STALE_PLAN = "stale_plan"


class ApplyError(RuntimeError):
    def __init__(
        self,
        code: ApplyErrorCode,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


class ApplyStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class ApplyStageStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    COMMITTED = "committed"
    FAILED = "failed"


@dataclass(frozen=True)
class ApplyItemResult:
    plan_id: str
    resource_type: str
    action: PlanAction
    database_id: int

    def __post_init__(self) -> None:
        if self.database_id <= 0:
            raise ValueError(
                "database_id must be positive"
            )


@dataclass(frozen=True)
class ApplyResult:
    status: ApplyStatus
    metadata_status: ApplyStageStatus
    raw_status: ApplyStageStatus
    items: tuple[ApplyItemResult, ...] = ()

    def __post_init__(self) -> None:
        if self.status == ApplyStatus.SUCCESS:
            if self.metadata_status == ApplyStageStatus.FAILED:
                raise ValueError(
                    "successful apply cannot have "
                    "failed METADATA stage"
                )
            if self.raw_status == ApplyStageStatus.FAILED:
                raise ValueError(
                    "successful apply cannot have "
                    "failed RAW stage"
                )

        elif self.status == ApplyStatus.FAILED:
            if self.metadata_status == ApplyStageStatus.COMMITTED:
                raise ValueError(
                    "failed apply cannot have "
                    "committed METADATA stage"
                )
            if self.raw_status == ApplyStageStatus.COMMITTED:
                raise ValueError(
                    "failed apply cannot have "
                    "committed RAW stage"
                )

        elif self.status == ApplyStatus.PARTIAL:
            if (
                self.metadata_status
                != ApplyStageStatus.COMMITTED
                or self.raw_status
                != ApplyStageStatus.FAILED
            ):
                raise ValueError(
                    "partial apply requires committed "
                    "METADATA and failed RAW"
                )

