from ..plan import (
    ExistingRef,
    PlanAction,
    PlannedRef,
    ResolvedPlanItem,
)
from .models import ApplyError, ApplyErrorCode

_RELATIONSHIP_FIELDS = {
    "site": {"parent": "site"},
    "sensor_model": {"sensor_type": "sensor_type"},
    "sensor": {"sensor_model": "sensor_model"},
    "location": {
        "site": "site",
        "location_type": "location_type",
    },
    "location_label": {"location": "location"},
    "deployment": {
        "sensor": "sensor",
        "location": "location",
        "variable": "variable",
    },
}


def _reference_dependency(
    reference: object,
    *,
    resource_type: str,
    nullable: bool,
    source: str,
    items_by_id: dict[str, ResolvedPlanItem],
) -> str | None:
    if reference is None and nullable:
        return None

    if not isinstance(reference, (ExistingRef, PlannedRef)):
        raise ApplyError(
            ApplyErrorCode.PLAN_NOT_APPLICABLE,
            f"{source} requires a resource reference",
        )

    if reference.resource_type != resource_type:
        raise ApplyError(
            ApplyErrorCode.PLAN_NOT_APPLICABLE,
            f"{source} requires a {resource_type} reference",
        )

    if isinstance(reference, ExistingRef):
        if (
            type(reference.database_id) is not int
            or reference.database_id <= 0
        ):
            raise ApplyError(
                ApplyErrorCode.PLAN_NOT_APPLICABLE,
                f"{source} requires a positive integer reference ID",
            )

        return None

    target = items_by_id.get(reference.plan_id)

    if (
        target is None
        or target.resource_type != resource_type
        or target.action != PlanAction.CREATE
    ):
        raise ApplyError(
            ApplyErrorCode.PLAN_NOT_APPLICABLE,
            f"{source} planned reference must target a matching "
            f"METADATA CREATE item: {reference.plan_id}",
        )

    return reference.plan_id


def metadata_reference_dependencies(
    items: tuple[ResolvedPlanItem, ...],
) -> dict[str, set[str]]:
    """Build reference dependencies after structural preparation."""

    items_by_id = {item.plan_id: item for item in items}
    dependencies: dict[str, set[str]] = {
        item.plan_id: set()
        for item in items
    }

    for item in items:
        fields = _RELATIONSHIP_FIELDS.get(item.resource_type, {})

        references = [
            (field, getattr(item.values, field), field)
            for field in fields
        ]

        if item.action == PlanAction.UPDATE:
            references.extend(
                (
                    change.field,
                    change.before,
                    f"{change.field}.before",
                )
                for change in item.changes
                if change.field in fields
            )

        for field, reference, label in references:
            source = f"{item.plan_id}.{label}"

            if (
                item.action == PlanAction.REUSE
                and isinstance(reference, PlannedRef)
            ):
                raise ApplyError(
                    ApplyErrorCode.PLAN_NOT_APPLICABLE,
                    f"{source}: REUSE cannot depend on a planned resource",
                )

            dependency = _reference_dependency(
                reference,
                resource_type=fields[field],
                nullable=(
                    item.resource_type == "site"
                    and field == "parent"
                ),
                source=source,
                items_by_id=items_by_id,
            )

            if dependency is not None:
                dependencies[item.plan_id].add(dependency)

    return dependencies


def order_metadata_items(
    items: tuple[ResolvedPlanItem, ...],
    dependencies: dict[str, set[str]],
) -> tuple[ResolvedPlanItem, ...]:
    """Select the earliest ready item until all items are ordered."""

    pending = list(items)
    completed: set[str] = set()
    ordered: list[ResolvedPlanItem] = []

    while pending:
        ready_index = next(
            (
                index
                for index, item in enumerate(pending)
                if dependencies[item.plan_id] <= completed
            ),
            None,
        )

        if ready_index is None:
            blocked = ", ".join(item.plan_id for item in pending)
            raise ApplyError(
                ApplyErrorCode.PLAN_NOT_APPLICABLE,
                "METADATA dependency cycle; blocked items: "
                f"{blocked}",
            )

        item = pending.pop(ready_index)
        ordered.append(item)
        completed.add(item.plan_id)

    return tuple(ordered)
