from ..plan import PlanAction, ResolvedPlan
from .combined_preparation import prepare_plan
from .context import ApplyContext
from .execution import execute_metadata_preparation
from .models import (
    ApplyError,
    ApplyErrorCode,
    ApplyExecutionError,
    ApplyItemResult,
    ApplyResult,
    ApplyStageStatus,
    ApplyStatus,
)
from .raw_execution import execute_raw_preparation
from .transactions import StageTransactionError, run_write_stage


def apply_plan(
    plan: ResolvedPlan,
    *,
    confirm_identity_changes: bool = False,
) -> ApplyResult:
    """Apply METADATA and RAW using sequential owned transactions.

    Both stages are prepared before connecting. Required deployment IDs
    are transferred to RAW only after METADATA commit is acknowledged.

    Preparation errors propagate directly. Ordinary execution and
    cleanup failures raise ApplyExecutionError carrying the known
    database outcome. There are no automatic retries.
    """
    prepared = prepare_plan(
        plan,
        confirm_identity_changes=confirm_identity_changes,
    )

    metadata_status = ApplyStageStatus.NOT_REQUIRED
    raw_status = ApplyStageStatus.NOT_REQUIRED

    # Complete stages that require no transaction. REUSE references
    # cannot depend on resources created by another stage.
    metadata_items = (
        ()
        if prepared.metadata.requires_writes
        else execute_metadata_preparation(
            None,
            prepared.metadata,
            ApplyContext(),
        )
    )
    raw_items = (
        ()
        if prepared.raw.requires_writes
        else execute_raw_preparation(
            None,
            prepared.raw,
            ApplyContext(),
        )
    )

    if prepared.metadata.requires_writes:
        try:
            metadata_items = run_write_stage(
                "dendroflow_metadata",
                lambda connection: execute_metadata_preparation(
                    connection,
                    prepared.metadata,
                    ApplyContext(),
                ),
            )
        except StageTransactionError as error:
            result = _combined_result(
                error.status,
                (
                    ApplyStageStatus.NOT_STARTED
                    if prepared.raw.requires_writes
                    else ApplyStageStatus.NOT_REQUIRED
                ),
                error.items + raw_items,
            )
            raise ApplyExecutionError(
                "METADATA stage did not finish cleanly",
                result=result,
            ) from error

        metadata_status = ApplyStageStatus.COMMITTED

    if prepared.raw.requires_writes:
        def execute_raw(connection: object) -> tuple[ApplyItemResult, ...]:
            context = ApplyContext()
            metadata_by_id = {
                item.plan_id: item
                for item in metadata_items
            }

            for plan_id in prepared.raw.required_metadata_plan_ids:
                item = metadata_by_id.get(plan_id)

                if (
                    metadata_status != ApplyStageStatus.COMMITTED
                    or item is None
                    or item.resource_type != "deployment"
                    or item.action is not PlanAction.CREATE
                    or type(item.database_id) is not int
                    or item.database_id <= 0
                ):
                    raise ApplyError(
                        ApplyErrorCode.UNRESOLVED_PLANNED_REF,
                        "committed deployment result is unavailable: "
                        f"{plan_id}",
                    )

                context.register(
                    plan_id=plan_id,
                    resource_type="deployment",
                    database_id=item.database_id,
                )

            return execute_raw_preparation(
                connection,
                prepared.raw,
                context,
            )

        try:
            raw_items = run_write_stage(
                "dendroflow_raw",
                execute_raw,
            )
        except StageTransactionError as error:
            result = _combined_result(
                metadata_status,
                error.status,
                metadata_items + error.items,
            )
            raise ApplyExecutionError(
                "RAW stage did not finish cleanly",
                result=result,
            ) from error

        raw_status = ApplyStageStatus.COMMITTED

    return _combined_result(
        metadata_status,
        raw_status,
        metadata_items + raw_items,
    )


def _combined_result(
    metadata_status: ApplyStageStatus,
    raw_status: ApplyStageStatus,
    items: tuple[ApplyItemResult, ...],
) -> ApplyResult:
    stages = (metadata_status, raw_status)

    if ApplyStageStatus.UNKNOWN in stages:
        status = ApplyStatus.UNKNOWN
    elif (
        metadata_status == ApplyStageStatus.COMMITTED
        and raw_status in {
            ApplyStageStatus.FAILED,
            ApplyStageStatus.NOT_STARTED,
        }
    ):
        status = ApplyStatus.PARTIAL
    elif ApplyStageStatus.FAILED in stages:
        status = ApplyStatus.FAILED
    else:
        status = ApplyStatus.SUCCESS

    return ApplyResult(
        status=status,
        metadata_status=metadata_status,
        raw_status=raw_status,
        items=items,
    )

