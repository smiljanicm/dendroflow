from enum import Enum


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