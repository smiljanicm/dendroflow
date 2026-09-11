from ..plan import PlanError, ResolvedPlan


def collect_plan_consistency_errors(
    plan: ResolvedPlan,
) -> tuple[PlanError, ...]:
    """Collect plan-wide consistency errors."""

    return ()

