from dataclasses import replace

from ..plan import (
    PlanAction,
    ResolvedDeploymentValues,
    ResolvedPlanItem,
)
from .models import ApplyError, ApplyErrorCode

_UNIQUE_FIELDS = {
    "site": ("site_code",),
    "location_type": ("type",),
    "sensor_type": ("type",),
    "variable": ("variable",),
    "sensor_model": ("manufacturer", "model"),
    "sensor": ("sensor_model", "serial_number"),
}


def _deployment_state(
    item: ResolvedPlanItem,
    *,
    before: bool = False,
) -> ResolvedDeploymentValues:
    assert isinstance(item.values, ResolvedDeploymentValues)

    if not before:
        return item.values

    previous_values = {
        change.field: change.before
        for change in item.changes
        if change.field in {
            "sensor",
            "variable",
            "valid_from",
            "valid_to",
        }
    }

    return replace(item.values, **previous_values)


def _deployment_states_overlap(
    first: ResolvedDeploymentValues,
    second: ResolvedDeploymentValues,
) -> bool:
    if first.sensor != second.sensor or first.variable != second.variable:
        return False

    return (
        second.valid_to is None
        or first.valid_from < second.valid_to
    ) and (
        first.valid_to is None
        or second.valid_from < first.valid_to
    )


def metadata_deployment_dependencies(
    items: tuple[ResolvedPlanItem, ...],
) -> dict[str, set[str]]:
    """Order deployment updates before operations needing their old space."""

    dependencies: dict[str, set[str]] = {
        item.plan_id: set()
        for item in items
    }

    deployments = [
        (item, _deployment_state(item))
        for item in items
        if item.resource_type == "deployment"
        and item.action in {PlanAction.CREATE, PlanAction.UPDATE}
    ]

    for index, (item, final_state) in enumerate(deployments):
        for previous_item, previous_state in deployments[:index]:
            if _deployment_states_overlap(final_state, previous_state):
                raise ApplyError(
                    ApplyErrorCode.PLAN_NOT_APPLICABLE,
                    "overlapping final deployment states: "
                    f"{previous_item.plan_id}, {item.plan_id}",
                )

    for holder, _ in deployments:
        if holder.action != PlanAction.UPDATE:
            continue

        old_state = _deployment_state(holder, before=True)

        for claimant, final_state in deployments:
            if claimant.plan_id == holder.plan_id:
                continue

            if _deployment_states_overlap(old_state, final_state):
                dependencies[claimant.plan_id].add(holder.plan_id)

    return dependencies


def _unique_key(
    item: ResolvedPlanItem,
    *,
    before: bool = False,
) -> tuple[object, ...] | None:
    fields = _UNIQUE_FIELDS.get(item.resource_type)

    if fields is None:
        return None

    values = {
        field: getattr(item.values, field)
        for field in fields
    }

    if before:
        for change in item.changes:
            if change.field in values:
                values[change.field] = change.before

    key = tuple(values[field] for field in fields)

    # These PostgreSQL UNIQUE constraints use distinct NULL semantics.
    if any(value is None for value in key):
        return None

    return key


def metadata_unique_dependencies(
    items: tuple[ResolvedPlanItem, ...],
) -> dict[str, set[str]]:
    """Order releases of unique keys before operations acquiring them."""

    dependencies: dict[str, set[str]] = {
        item.plan_id: set()
        for item in items
    }

    for holder in items:
        if holder.action != PlanAction.UPDATE:
            continue

        old_key = _unique_key(holder, before=True)
        new_key = _unique_key(holder)

        if old_key is None or old_key == new_key:
            continue

        for claimant in items:
            if claimant.action not in {
                PlanAction.CREATE,
                PlanAction.UPDATE,
            }:
                continue

            if (
                claimant.plan_id == holder.plan_id
                or claimant.resource_type != holder.resource_type
            ):
                continue

            if _unique_key(claimant) == old_key:
                dependencies[claimant.plan_id].add(holder.plan_id)

    return dependencies
