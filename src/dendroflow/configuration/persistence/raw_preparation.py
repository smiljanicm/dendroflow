from collections.abc import Mapping
from dataclasses import dataclass

from ..plan import (
    ExistingRef,
    PlanAction,
    PlannedRef,
    ResolvedDeploymentValues,
    ResolvedFileValues,
    ResolvedInterfaceValues,
    ResolvedPlan,
    ResolvedPlanItem,
)
from .models import ApplyError, ApplyErrorCode
from .preflight import validate_plan_for_apply

_RAW_VALUE_TYPES = {
    "file": ResolvedFileValues,
    "interface": ResolvedInterfaceValues,
}


@dataclass(frozen=True)
class RawPreparation:
    """Prepared RAW operations and their external METADATA dependencies."""

    items: tuple[ResolvedPlanItem, ...]
    execution_items: tuple[ResolvedPlanItem, ...]
    required_metadata_plan_ids: tuple[str, ...] = ()

    @property
    def requires_writes(self) -> bool:
        return any(
            item.action == PlanAction.CREATE
            for item in self.items
        )


def prepare_raw_plan(
    plan: ResolvedPlan,
    *,
    confirm_identity_changes: bool = False,
    allow_metadata_dependencies: bool = False,
) -> RawPreparation:
    """Prepare RAW operations without opening a database connection.

    By default, only RAW-only plans are accepted.

    Combined preparation may inspect METADATA CREATE targets, but does
    not validate or execute the entire METADATA stage. The orchestrator
    must prepare that stage separately and commit it before supplying
    generated deployment IDs to RAW execution.
    """
    validate_plan_for_apply(
        plan,
        confirm_identity_changes=confirm_identity_changes,
    )

    if plan.metadata_items and not allow_metadata_dependencies:
        raise _invalid(
            "RAW-only apply does not accept METADATA items"
        )

    seen_plan_ids: set[str] = set()

    for item in plan.items:
        if item.plan_id in seen_plan_ids:
            raise _invalid(
                f"duplicate plan_id: {item.plan_id}"
            )
        seen_plan_ids.add(item.plan_id)

    for item in plan.raw_items:
        _validate_raw_item(item)

    raw_by_id = {
        item.plan_id: item
        for item in plan.raw_items
    }
    metadata_by_id = {
        item.plan_id: item
        for item in plan.metadata_items
    }
    dependencies: dict[str, set[str]] = {
        item.plan_id: set()
        for item in plan.raw_items
    }
    required_metadata: set[str] = set()

    for item in plan.raw_items:
        if item.resource_type != "interface":
            continue

        for field in ("file", "deployment"):
            reference = getattr(item.values, field)
            source = f"{item.plan_id}.{field}"

            if not isinstance(reference, (ExistingRef, PlannedRef)):
                raise _invalid(
                    f"{source} requires a resource reference"
                )

            if reference.resource_type != field:
                raise _invalid(
                    f"{source} requires a {field} reference"
                )

            if isinstance(reference, ExistingRef):
                if (
                    type(reference.database_id) is not int
                    or reference.database_id <= 0
                ):
                    raise _invalid(
                        f"{source} requires a positive integer reference ID"
                    )
                continue

            if item.action == PlanAction.REUSE:
                raise _invalid(
                    f"{source}: REUSE cannot depend on a planned resource"
                )

            if field == "file":
                target = raw_by_id.get(reference.plan_id)
                values_type = ResolvedFileValues
            else:
                if not allow_metadata_dependencies:
                    raise _invalid(
                        f"{source}: RAW-only apply requires "
                        "an existing deployment"
                    )
                target = metadata_by_id.get(reference.plan_id)
                values_type = ResolvedDeploymentValues

            if (
                target is None
                or target.resource_type != field
                or target.action is not PlanAction.CREATE
                or target.database_id is not None
                or not isinstance(target.values, values_type)
            ):
                raise _invalid(
                    f"{source} planned reference must target "
                    f"a matching {field} CREATE item: "
                    f"{reference.plan_id}"
                )

            if field == "file":
                dependencies[item.plan_id].add(reference.plan_id)
            else:
                required_metadata.add(reference.plan_id)

    return RawPreparation(
        items=plan.raw_items,
        execution_items=_order_raw_items(
            plan.raw_items,
            dependencies,
        ),
        required_metadata_plan_ids=tuple(sorted(required_metadata)),
    )


def _validate_raw_item(item: ResolvedPlanItem) -> None:
    values_type = _RAW_VALUE_TYPES.get(item.resource_type)

    if values_type is None:
        raise _invalid(
            f"unsupported RAW resource type: {item.resource_type}"
        )

    if (
        not isinstance(item.action, PlanAction)
        or item.action not in {PlanAction.CREATE, PlanAction.REUSE}
    ):
        raise _invalid(
            f"unsupported RAW action: {item.action}"
        )

    if not isinstance(item.values, values_type):
        raise _invalid(
            f"{item.resource_type} requires {values_type.__name__}"
        )

    if item.action == PlanAction.REUSE and (
        type(item.database_id) is not int
        or item.database_id <= 0
    ):
        raise _invalid(
            f"{item.resource_type} requires "
            "a positive integer database_id"
        )

    if item.resource_type == "file" and not isinstance(
        item.values.reader_config,
        Mapping,
    ):
        raise _invalid(
            f"{item.plan_id}: reader_config must be a mapping"
        )


def _order_raw_items(
    items: tuple[ResolvedPlanItem, ...],
    dependencies: dict[str, set[str]],
) -> tuple[ResolvedPlanItem, ...]:
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
            raise _invalid(
                f"RAW dependency cycle; blocked items: {blocked}"
            )

        item = pending.pop(ready_index)
        ordered.append(item)
        completed.add(item.plan_id)

    return tuple(ordered)


def _invalid(message: str) -> ApplyError:
    return ApplyError(
        ApplyErrorCode.PLAN_NOT_APPLICABLE,
        message,
    )
