from ..plan import PlanAction, PlannedRef
from .context import ApplyContext
from .models import ApplyError, ApplyErrorCode, ApplyItemResult
from .raw import create_raw_item
from .raw_preparation import RawPreparation


def execute_raw_preparation(
    connection: object,
    prepared: RawPreparation,
    context: ApplyContext,
) -> tuple[ApplyItemResult, ...]:
    """Execute prepared RAW operations without transaction management.

    The caller supplies a preparation from prepare_raw_plan() and an
    attempt-local context. Required METADATA registrations must come
    from committed METADATA work; this function cannot verify commit
    status.

    Results describe executed operations, not committed transactions.
    After a failure, the caller must roll back and discard the context.
    """
    for plan_id in prepared.required_metadata_plan_ids:
        context.resolve(
            PlannedRef(
                resource_type="deployment",
                plan_id=plan_id,
            )
        )

    results: dict[str, ApplyItemResult] = {}

    for item in prepared.execution_items:
        if item.action == PlanAction.CREATE:
            result = create_raw_item(connection, item, context)

        elif item.action == PlanAction.REUSE:
            assert item.database_id is not None

            result = ApplyItemResult(
                plan_id=item.plan_id,
                resource_type=item.resource_type,
                action=item.action,
                database_id=item.database_id,
            )

        else:
            raise ApplyError(
                ApplyErrorCode.PLAN_NOT_APPLICABLE,
                f"unsupported RAW action: {item.action}",
            )

        results[item.plan_id] = result

    return tuple(
        results[item.plan_id]
        for item in prepared.items
    )

