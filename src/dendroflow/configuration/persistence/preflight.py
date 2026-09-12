from ..plan import ResolvedPlan
from .models import ApplyError, ApplyErrorCode


def validate_plan_for_apply(
    plan: ResolvedPlan,
    *,
    confirm_identity_changes: bool = False,
) -> None:
    """Validate that a resolved plan may enter persistence."""

    if not plan.can_apply:
        raise ApplyError(
            ApplyErrorCode.PLAN_NOT_APPLICABLE,
            "plan contains errors and cannot be applied",
        )

    if (
        plan.requires_confirmation
        and not confirm_identity_changes
    ):
        raise ApplyError(
            ApplyErrorCode.CONFIRMATION_REQUIRED,
            "plan contains changes that require confirmation",
        )