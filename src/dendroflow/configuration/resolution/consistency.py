from dataclasses import dataclass
from datetime import datetime

from ..plan import (
    ExistingRef,
    PlanAction,
    PlanError,
    PlanErrorCode,
    PlannedRef,
    ResolvedDeploymentValues,
    ResolvedInterfaceValues,
    ResolvedLocationTypeValues,
    ResolvedLocationValues,
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSensorModelValues,
    ResolvedSensorTypeValues,
    ResolvedSensorValues,
    ResolvedSiteValues,
    ResolvedVariableValues,
)


@dataclass(frozen=True)
class ExistingDeploymentState:
    deployment_id: int
    sensor_id: int
    variable_id: int
    valid_from: datetime
    valid_to: datetime | None

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


def _intervals_overlap(
    first_start,
    first_end,
    second_start,
    second_end,
) -> bool:
    """Return whether two half-open intervals overlap."""

    first_before_second_end = (
        second_end is None
        or first_start < second_end
    )
    second_before_first_end = (
        first_end is None
        or second_start < first_end
    )

    return (
        first_before_second_end
        and second_before_first_end
    )


def _deployment_resource_key(
    item: ResolvedPlanItem,
) -> tuple[str, object]:
    if item.action == PlanAction.UPDATE:
        assert item.database_id is not None
        return ("existing", item.database_id)

    return ("planned", item.plan_id)


def _collect_deployment_overlap_errors(
    plan: ResolvedPlan,
) -> list[PlanError]:
    errors: list[PlanError] = []

    previous_deployments: list[
        ResolvedPlanItem
    ] = []

    for item in plan.metadata_items:
        if item.resource_type != "deployment":
            continue

        if item.action not in {
            PlanAction.CREATE,
            PlanAction.UPDATE,
        }:
            continue

        assert isinstance(
            item.values,
            ResolvedDeploymentValues,
        )

        item_resource = _deployment_resource_key(
            item
        )

        for previous in previous_deployments:
            assert isinstance(
                previous.values,
                ResolvedDeploymentValues,
            )

            previous_resource = (
                _deployment_resource_key(previous)
            )

            if previous_resource == item_resource:
                continue

            same_exclusion_key = (
                previous.values.sensor
                == item.values.sensor
                and previous.values.variable
                == item.values.variable
            )

            if not same_exclusion_key:
                continue

            if not _intervals_overlap(
                previous.values.valid_from,
                previous.values.valid_to,
                item.values.valid_from,
                item.values.valid_to,
            ):
                continue

            errors.append(
                PlanError(
                    code=PlanErrorCode.CONFLICT,
                    resource_type="deployment",
                    source_path=item.source_path,
                    message=(
                        "deployment validity interval "
                        "overlaps another planned "
                        "deployment for the same "
                        "sensor and variable"
                    ),
                )
            )
            break

        previous_deployments.append(item)

    return errors


def _collect_existing_deployment_overlap_errors(
    plan: ResolvedPlan,
    existing_deployments: tuple[
        ExistingDeploymentState, ...
    ],
) -> list[PlanError]:
    errors: list[PlanError] = []

    updated_deployment_ids = {
        item.database_id
        for item in plan.metadata_items
        if item.resource_type == "deployment"
        and item.action == PlanAction.UPDATE
    }

    for item in plan.metadata_items:
        if item.resource_type != "deployment":
            continue

        if item.action not in {
            PlanAction.CREATE,
            PlanAction.UPDATE,
        }:
            continue

        assert isinstance(
            item.values,
            ResolvedDeploymentValues,
        )

        sensor = item.values.sensor
        variable = item.values.variable

        # Planned resources cannot have persisted deployment history.
        if not isinstance(sensor, ExistingRef):
            continue

        if not isinstance(variable, ExistingRef):
            continue

        for existing in existing_deployments:
            # Final UPDATE values are checked against other planned
            # deployments by _collect_deployment_overlap_errors().
            # Their persisted snapshots are no longer final states.
            if existing.deployment_id in updated_deployment_ids:
                continue

            if existing.sensor_id != sensor.database_id:
                continue

            if existing.variable_id != variable.database_id:
                continue

            if not _intervals_overlap(
                item.values.valid_from,
                item.values.valid_to,
                existing.valid_from,
                existing.valid_to,
            ):
                continue

            errors.append(
                PlanError(
                    code=PlanErrorCode.CONFLICT,
                    resource_type="deployment",
                    source_path=item.source_path,
                    message=(
                        "deployment validity interval "
                        "overlaps an existing deployment "
                        "for the same sensor and variable"
                    ),
                )
            )
            break

    return errors


def _collect_planned_ref_errors(
    plan: ResolvedPlan,
) -> list[PlanError]:
    errors: list[PlanError] = []

    planned_creates = {
        (item.resource_type, item.plan_id)
        for item in plan.items
        if item.action == PlanAction.CREATE
    }

    for item in plan.items:
        references: tuple[object, ...]

        if isinstance(
            item.values,
            ResolvedDeploymentValues,
        ):
            references = (
                item.values.sensor,
                item.values.location,
                item.values.variable,
            )

        elif isinstance(
            item.values,
            ResolvedInterfaceValues,
        ):
            references = (
                item.values.file,
                item.values.deployment,
            )

        elif isinstance(
            item.values,
            ResolvedSensorValues,
        ):
            references = (
                item.values.sensor_model,
            )

        elif isinstance(
            item.values,
            ResolvedSensorModelValues,
        ):
            references = (
                item.values.sensor_type,
            )

        elif isinstance(
            item.values,
            ResolvedLocationValues,
        ):
            references = (
                item.values.site,
                item.values.location_type,
            )

        else:
            continue

        for reference in references:
            if not isinstance(reference, PlannedRef):
                continue

            target = (
                reference.resource_type,
                reference.plan_id,
            )

            if target in planned_creates:
                continue

            errors.append(
                PlanError(
                    code=PlanErrorCode.CONFLICT,
                    resource_type=item.resource_type,
                    source_path=item.source_path,
                    message=(
                        "planned reference does not "
                        "resolve to a matching CREATE item"
                    ),
                )
            )
            break

    return errors



def _final_identity(
    item: ResolvedPlanItem,
) -> tuple[object, ...] | None:
    """Return the resource's final natural identity."""

    if item.identity is not None:
        return tuple(sorted(item.identity.components))

    if item.resource_type == "site":
        assert isinstance(
            item.values,
            ResolvedSiteValues,
        )
        return (item.values.site_code,)

    if item.resource_type == "location_type":
        assert isinstance(
            item.values,
            ResolvedLocationTypeValues,
        )
        return (item.values.type,)

    if item.resource_type == "sensor_type":
        assert isinstance(
            item.values,
            ResolvedSensorTypeValues,
        )
        return (item.values.type,)

    if item.resource_type == "variable":
        assert isinstance(
            item.values,
            ResolvedVariableValues,
        )
        return (item.values.variable,)

    if item.resource_type == "sensor":
        assert isinstance(
            item.values,
            ResolvedSensorValues,
        )
        return (
            item.values.sensor_model,
            item.values.serial_number,
        )

    if item.resource_type == "sensor_model":
        assert isinstance(
            item.values,
            ResolvedSensorModelValues,
        )
        return (
            item.values.manufacturer,
            item.values.model,
        )

    return None


def _identity_resource_key(
    item: ResolvedPlanItem,
) -> tuple[str, object]:
    if item.action in {
        PlanAction.REUSE,
        PlanAction.UPDATE,
    }:
        assert item.database_id is not None
        return ("existing", item.database_id)

    return ("planned", item.plan_id)


def _collect_final_identity_errors(
    plan: ResolvedPlan,
) -> list[PlanError]:
    errors: list[PlanError] = []

    updated_resources = {
        (
            item.resource_type,
            item.database_id,
        )
        for item in plan.metadata_items
        if item.action == PlanAction.UPDATE
    }

    seen: dict[
        tuple[str, tuple[object, ...]],
        tuple[str, object],
    ] = {}

    for item in plan.metadata_items:
        if item.action not in {
            PlanAction.CREATE,
            PlanAction.REUSE,
            PlanAction.UPDATE,
        }:
            continue

        # A REUSE row followed by an UPDATE is not a separate
        # final state. The UPDATE represents that persisted row.
        if (
            item.action == PlanAction.REUSE
            and (
                item.resource_type,
                item.database_id,
            )
            in updated_resources
        ):
            continue

        identity = _final_identity(item)

        if identity is None:
            continue

        identity_key = (
            item.resource_type,
            identity,
        )
        resource = _identity_resource_key(item)

        previous = seen.get(identity_key)

        if (
            previous is not None
            and previous != resource
        ):
            errors.append(
                PlanError(
                    code=PlanErrorCode.CONFLICT,
                    resource_type=item.resource_type,
                    source_path=item.source_path,
                    message=(
                        f"{item.resource_type} final identity "
                        "conflicts with another planned "
                        "resource state"
                    ),
                )
            )
            continue

        seen[identity_key] = resource

    return errors


def collect_plan_consistency_errors(
    plan: ResolvedPlan,
    *,
    existing_deployments: tuple[
        ExistingDeploymentState, ...
    ] = (),
) -> tuple[PlanError, ...]:
    """Collect plan-wide consistency errors."""

    errors: list[PlanError] = []

    errors.extend(
        _collect_duplicate_update_errors(plan)
    )
    errors.extend(
        _collect_final_identity_errors(plan)
    )
    errors.extend(
        _collect_deployment_overlap_errors(plan)
    )
    errors.extend(
        _collect_existing_deployment_overlap_errors(
            plan,
            existing_deployments,
        )
    )
    errors.extend(
        _collect_planned_ref_errors(plan)
    )

    return tuple(errors)

