from dendroflow import database

from ..plan import ResolvedPlan
from .context import ApplyContext
from .execution import execute_metadata_preparation
from .models import ApplyResult, ApplyStageStatus, ApplyStatus
from .preparation import prepare_metadata_plan
from .raw_execution import execute_raw_preparation
from .raw_preparation import prepare_raw_plan


def apply_metadata_plan(
    plan: ResolvedPlan,
    *,
    confirm_identity_changes: bool = False,
) -> ApplyResult:
    """Apply a METADATA-only plan using an owned transaction.

    Preparation completes before connecting. Each call uses a fresh
    context, and write results are returned only after commit succeeds.

    Preparation, connection, execution, and commit errors propagate
    to the caller. No automatic retry is performed.
    """
    prepared = prepare_metadata_plan(
        plan,
        confirm_identity_changes=confirm_identity_changes,
    )
    context = ApplyContext()

    if prepared.requires_writes:
        with database.connect("dendroflow_metadata") as connection:
            items = execute_metadata_preparation(
                connection,
                prepared,
                context,
            )

        metadata_status = ApplyStageStatus.COMMITTED
    else:
        # Empty and REUSE-only preparations perform no database calls.
        items = execute_metadata_preparation(
            None,
            prepared,
            context,
        )
        metadata_status = ApplyStageStatus.NOT_REQUIRED

    return ApplyResult(
        status=ApplyStatus.SUCCESS,
        metadata_status=metadata_status,
        raw_status=ApplyStageStatus.NOT_REQUIRED,
        items=items,
    )

def apply_raw_plan(
    plan: ResolvedPlan,
    *,
    confirm_identity_changes: bool = False,
) -> ApplyResult:
    """Apply a RAW-only plan using an owned transaction.

    Preparation completes before connecting. Deployment references
    must identify existing resources.

    Each call uses a fresh context. Write results are returned only
    after commit succeeds. Errors propagate without automatic retries.
    """
    prepared = prepare_raw_plan(
        plan,
        confirm_identity_changes=confirm_identity_changes,
    )
    context = ApplyContext()

    if prepared.requires_writes:
        with database.connect("dendroflow_raw") as connection:
            items = execute_raw_preparation(
                connection,
                prepared,
                context,
            )

        raw_status = ApplyStageStatus.COMMITTED
    else:
        items = execute_raw_preparation(
            None,
            prepared,
            context,
        )
        raw_status = ApplyStageStatus.NOT_REQUIRED

    return ApplyResult(
        status=ApplyStatus.SUCCESS,
        metadata_status=ApplyStageStatus.NOT_REQUIRED,
        raw_status=raw_status,
        items=items,
    )
