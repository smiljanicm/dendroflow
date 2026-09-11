from ..plan import (
    PlanAction,
    PlanError,
    PlanErrorCode,
    ResolvedPlan,
    ResolvedSensorValues,
)


def _collect_duplicate_update_errors(
    plan: ResolvedPlan,
) -> list[PlanError]:
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

    return errors


def _collect_sensor_identity_errors(
    plan: ResolvedPlan,
) -> list[PlanError]:
    errors: list[PlanError] = []

    seen: dict[
        tuple[object, str],
        tuple[str, object],
    ] = {}

    for item in plan.metadata_items:
        if item.resource_type != "sensor":
            continue

        if item.action not in {
            PlanAction.CREATE,
            PlanAction.UPDATE,
        }:
            continue

        assert isinstance(
            item.values,
            ResolvedSensorValues,
        )

        identity = (
            item.values.sensor_model,
            item.values.serial_number,
        )

        if item.action == PlanAction.UPDATE:
            assert item.database_id is not None
            resource = (
                "existing",
                item.database_id,
            )
        else:
            resource = (
                "planned",
                item.plan_id,
            )

        previous = seen.get(identity)

        if previous is not None and previous != resource:
            errors.append(
                PlanError(
                    code=PlanErrorCode.CONFLICT,
                    resource_type="sensor",
                    source_path=item.source_path,
                    message=(
                        "sensor final identity conflicts "
                        "with another planned sensor state"
                    ),
                )
            )
            continue

        seen[identity] = resource

    return errors


def collect_plan_consistency_errors(
    plan: ResolvedPlan,
) -> tuple[PlanError, ...]:
    """Collect plan-wide consistency errors."""

    errors: list[PlanError] = []

    errors.extend(
        _collect_duplicate_update_errors(plan)
    )
    errors.extend(
        _collect_sensor_identity_errors(plan)
    )

    return tuple(errors)

