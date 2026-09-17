from dataclasses import dataclass

from ..plan import (
    PlanAction,
    ResolvedDeploymentValues,
    ResolvedLocationLabelValues,
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
from .constraints import (
    metadata_deployment_dependencies,
    metadata_unique_dependencies,
)
from .models import ApplyError, ApplyErrorCode
from .ordering import (
    metadata_reference_dependencies,
    order_metadata_items,
)
from .preflight import validate_plan_for_apply

_METADATA_VALUE_TYPES = {
    "site": ResolvedSiteValues,
    "location_type": ResolvedLocationTypeValues,
    "sensor_type": ResolvedSensorTypeValues,
    "variable": ResolvedVariableValues,
    "sensor_model": ResolvedSensorModelValues,
    "sensor": ResolvedSensorValues,
    "location": ResolvedLocationValues,
    "location_label": ResolvedLocationLabelValues,
    "deployment": ResolvedDeploymentValues,
}


@dataclass(frozen=True)
class MetadataPreparation:
    """Original items and their prepared execution order.

    Includes reference, unique-key, and deployment-interval dependencies.
    """

    items: tuple[ResolvedPlanItem, ...]
    execution_items: tuple[ResolvedPlanItem, ...]

    @property
    def requires_writes(self) -> bool:
        return any(
            item.action in {PlanAction.CREATE, PlanAction.UPDATE}
            for item in self.items
        )


def prepare_metadata_plan(
    plan: ResolvedPlan,
    *,
    confirm_identity_changes: bool = False,
) -> MetadataPreparation:
    """Check the METADATA apply boundary without database access."""

    validate_plan_for_apply(
        plan,
        confirm_identity_changes=confirm_identity_changes,
    )

    if plan.raw_items:
        raise ApplyError(
            ApplyErrorCode.PLAN_NOT_APPLICABLE,
            "METADATA-only apply does not accept RAW items",
        )

    seen_plan_ids: set[str] = set()
    seen_updates: set[tuple[str, int]] = set()

    for item in plan.metadata_items:
        if item.plan_id in seen_plan_ids:
            raise ApplyError(
                ApplyErrorCode.PLAN_NOT_APPLICABLE,
                f"duplicate METADATA plan_id: {item.plan_id}",
            )

        seen_plan_ids.add(item.plan_id)

        values_type = _METADATA_VALUE_TYPES.get(item.resource_type)

        if values_type is None:
            raise ApplyError(
                ApplyErrorCode.PLAN_NOT_APPLICABLE,
                "unsupported METADATA resource type: "
                f"{item.resource_type}",
            )

        if not isinstance(item.action, PlanAction):
            raise ApplyError(
                ApplyErrorCode.PLAN_NOT_APPLICABLE,
                f"unsupported METADATA action: {item.action}",
            )

        if (
            item.resource_type == "location_label"
            and item.action == PlanAction.UPDATE
        ):
            raise ApplyError(
                ApplyErrorCode.PLAN_NOT_APPLICABLE,
                "location_label UPDATE is not supported",
            )

        if not isinstance(item.values, values_type):
            raise ApplyError(
                ApplyErrorCode.PLAN_NOT_APPLICABLE,
                f"{item.resource_type} requires {values_type.__name__}",
            )

        if item.action in {PlanAction.REUSE, PlanAction.UPDATE} and (
            type(item.database_id) is not int
            or item.database_id <= 0
        ):
            raise ApplyError(
                ApplyErrorCode.PLAN_NOT_APPLICABLE,
                f"{item.resource_type} requires "
                "a positive integer database_id",
            )

        if item.action == PlanAction.UPDATE:
            target = (item.resource_type, item.database_id)

            if target in seen_updates:
                raise ApplyError(
                    ApplyErrorCode.PLAN_NOT_APPLICABLE,
                    "duplicate METADATA UPDATE target: "
                    f"{item.resource_type} {item.database_id}",
                )

            seen_updates.add(target)

    dependencies = metadata_reference_dependencies(plan.metadata_items)

    for constraint_dependencies in (
        metadata_unique_dependencies(plan.metadata_items),
        metadata_deployment_dependencies(plan.metadata_items),
    ):
        for plan_id, required_items in constraint_dependencies.items():
            dependencies[plan_id].update(required_items)

    execution_items = order_metadata_items(
        plan.metadata_items,
        dependencies,
    )

    return MetadataPreparation(
        items=plan.metadata_items,
        execution_items=execution_items,
    )  
