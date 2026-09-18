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
    UNKNOWN = "unknown"


class ApplyStageStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    NOT_STARTED = "not_started"
    COMMITTED = "committed"
    FAILED = "failed"
    UNKNOWN = "unknown"


_VALID_STAGE_STATES = {
    ApplyStatus.SUCCESS: frozenset(
        {
            (
                ApplyStageStatus.NOT_REQUIRED,
                ApplyStageStatus.NOT_REQUIRED,
            ),
            (
                ApplyStageStatus.COMMITTED,
                ApplyStageStatus.NOT_REQUIRED,
            ),
            (
                ApplyStageStatus.NOT_REQUIRED,
                ApplyStageStatus.COMMITTED,
            ),
            (
                ApplyStageStatus.COMMITTED,
                ApplyStageStatus.COMMITTED,
            ),
        }
    ),
    ApplyStatus.FAILED: frozenset(
        {
            (
                ApplyStageStatus.FAILED,
                ApplyStageStatus.NOT_REQUIRED,
            ),
            (
                ApplyStageStatus.FAILED,
                ApplyStageStatus.NOT_STARTED,
            ),
            (
                ApplyStageStatus.NOT_REQUIRED,
                ApplyStageStatus.FAILED,
            ),
        }
    ),
    ApplyStatus.PARTIAL: frozenset(
        {
            (
                ApplyStageStatus.COMMITTED,
                ApplyStageStatus.FAILED,
            ),
            (
                ApplyStageStatus.COMMITTED,
                ApplyStageStatus.NOT_STARTED,
            ),
        }
    ),
    ApplyStatus.UNKNOWN: frozenset(
        {
            (
                ApplyStageStatus.UNKNOWN,
                ApplyStageStatus.NOT_REQUIRED,
            ),
            (
                ApplyStageStatus.UNKNOWN,
                ApplyStageStatus.NOT_STARTED,
            ),
            (
                ApplyStageStatus.NOT_REQUIRED,
                ApplyStageStatus.UNKNOWN,
            ),
            (
                ApplyStageStatus.COMMITTED,
                ApplyStageStatus.UNKNOWN,
            ),
        }
    ),
}


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
    """Database outcome of an apply attempt.

    Stage combinations follow METADATA-before-RAW execution.

    Coordinators must include only item results from completed stages:
    committed writes and completed REUSE operations. Results from failed,
    unstarted, or uncertain stages must not be reported as applied.
    """

    status: ApplyStatus
    metadata_status: ApplyStageStatus
    raw_status: ApplyStageStatus
    items: tuple[ApplyItemResult, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, ApplyStatus):
            raise TypeError("status must be an ApplyStatus")

        if not isinstance(self.metadata_status, ApplyStageStatus):
            raise TypeError(
                "metadata_status must be an ApplyStageStatus"
            )

        if not isinstance(self.raw_status, ApplyStageStatus):
            raise TypeError(
                "raw_status must be an ApplyStageStatus"
            )

        stages = (self.metadata_status, self.raw_status)

        if stages not in _VALID_STAGE_STATES[self.status]:
            raise ValueError(
                "invalid apply outcome: "
                f"status={self.status.value}, "
                f"metadata={self.metadata_status.value}, "
                f"raw={self.raw_status.value}"
            )


class ApplyExecutionError(RuntimeError):
    """Execution or cleanup error carrying the known database outcome.

    Raise with explicit exception chaining to preserve the original
    error: raise ApplyExecutionError(...) from cause.

    The result may be SUCCESS if all required work completed before
    cleanup failed. An exception does not by itself imply rollback.
    """

    def __init__(
        self,
        message: str,
        *,
        result: ApplyResult,
    ) -> None:
        super().__init__(message)
        self.result = result
