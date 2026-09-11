from ..plan import (
    PlanAction,
    PlanError,
    PlanErrorCode,
    ResolvedPlan,
)


def collect_plan_consistency_errors(
    plan: ResolvedPlan,
) -> tuple[PlanError, ...]:
    """Collect plan-wide consistency errors."""

    errors: list[PlanError] = []

    seen_updates: set[tuple[str, int]] = set()

    for item in plan.items:
        if item.action != PlanAction.UPDATE:
            continue

        assert item.database_id is not None

        key = (
            item.resource_type,
            item.database_id,
        )

        if key in seen_updates:
            errors.append(
                PlanError(
                    code=PlanErrorCode.CONFLICT,
                    resource_type=item.resource_type,
                    source_path=item.source_path,
                    message=(
                        "resource is targeted by more than "
                        "one update"
                    ),
                )
            )
            continue

        seen_updates.add(key)

    return tuple(errors)

