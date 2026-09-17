from ..plan import PlanAction
from .context import ApplyContext
from .metadata import create_metadata_item
from .models import ApplyError, ApplyErrorCode, ApplyItemResult
from .preparation import MetadataPreparation
from .updates import update_metadata_item


def execute_metadata_preparation(
    connection: object,
    prepared: MetadataPreparation,
    context: ApplyContext,
) -> tuple[ApplyItemResult, ...]:
    """Execute prepared METADATA operations without transaction management.

    The caller supplies a preparation from prepare_metadata_plan(),
    a connection, and an attempt-local context.

    Results describe executed operations, not committed transactions.
    After a failure, the caller must roll back and discard the context.
    """

    results: dict[str, ApplyItemResult] = {}

    for item in prepared.execution_items:
        if item.action == PlanAction.CREATE:
            result = create_metadata_item(connection, item, context)

        elif item.action == PlanAction.UPDATE:
            result = update_metadata_item(connection, item, context)

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
                f"unsupported METADATA action: {item.action}",
            )

        results[item.plan_id] = result

    return tuple(
        results[item.plan_id]
        for item in prepared.items
    )
