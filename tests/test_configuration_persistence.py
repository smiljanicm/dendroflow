import pytest

from dendroflow.configuration.persistence.context import (
    ApplyContext,
)
from dendroflow.configuration.persistence.models import (
    ApplyError,
    ApplyErrorCode,
    ApplyItemResult,
    ApplyResult,
    ApplyStageStatus,
    ApplyStatus,
)
from dendroflow.configuration.persistence.preflight import (
    validate_plan_for_apply,
)
from dendroflow.configuration.plan import (
    ExistingRef,
    FieldChange,
    PlanAction,
    PlanError,
    PlanErrorCode,
    PlannedRef,
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSensorValues,
)


def _identity_changing_sensor_update() -> ResolvedPlanItem:
    return ResolvedPlanItem(
        plan_id="updates.sensors[0]",
        resource_type="sensor",
        action=PlanAction.UPDATE,
        database_id=17,
        values=ResolvedSensorValues(
            sensor_model=ExistingRef(
                resource_type="sensor_model",
                database_id=3,
            ),
            serial_number="NEW123",
            description=None,
        ),
        changes=(
            FieldChange(
                field="serial_number",
                before="OLD123",
                after="NEW123",
                identity_change=True,
            ),
        ),
        source_path="updates.sensors[0]",
    )


def test_empty_plan_passes_apply_preflight():
    plan = ResolvedPlan()

    validate_plan_for_apply(plan)


def test_plan_with_errors_is_not_applicable():
    plan = ResolvedPlan(
        errors=(
            PlanError(
                code=PlanErrorCode.CONFLICT,
                resource_type="sensor",
                source_path="updates.sensors[0]",
                message="test conflict",
            ),
        ),
    )

    with pytest.raises(ApplyError) as exc_info:
        validate_plan_for_apply(plan)

    assert (
        exc_info.value.code
        == ApplyErrorCode.PLAN_NOT_APPLICABLE
    )


def test_identity_change_requires_confirmation():
    plan = ResolvedPlan(
        metadata_items=(
            _identity_changing_sensor_update(),
        ),
    )

    assert plan.can_apply is True
    assert plan.requires_confirmation is True

    with pytest.raises(ApplyError) as exc_info:
        validate_plan_for_apply(plan)

    assert (
        exc_info.value.code
        == ApplyErrorCode.CONFIRMATION_REQUIRED
    )


def test_confirmed_identity_change_passes_apply_preflight():
    plan = ResolvedPlan(
        metadata_items=(
            _identity_changing_sensor_update(),
        ),
    )

    validate_plan_for_apply(
        plan,
        confirm_identity_changes=True,
    )


def test_non_identity_update_does_not_require_confirmation():
    item = ResolvedPlanItem(
        plan_id="updates.sensors[0]",
        resource_type="sensor",
        action=PlanAction.UPDATE,
        database_id=17,
        values=ResolvedSensorValues(
            sensor_model=ExistingRef(
                resource_type="sensor_model",
                database_id=3,
            ),
            serial_number="OLD123",
            description="new description",
        ),
        changes=(
            FieldChange(
                field="description",
                before="old description",
                after="new description",
                identity_change=False,
            ),
        ),
        source_path="updates.sensors[0]",
    )

    plan = ResolvedPlan(
        metadata_items=(item,),
    )

    assert plan.can_apply is True
    assert plan.requires_confirmation is False

    validate_plan_for_apply(plan)


def test_confirmation_does_not_make_invalid_plan_applicable():
    plan = ResolvedPlan(
        errors=(
            PlanError(
                code=PlanErrorCode.CONFLICT,
                resource_type="sensor",
                source_path="updates.sensors[0]",
                message="test conflict",
            ),
        ),
    )

    with pytest.raises(ApplyError) as exc_info:
        validate_plan_for_apply(
            plan,
            confirm_identity_changes=True,
        )

    assert (
        exc_info.value.code
        == ApplyErrorCode.PLAN_NOT_APPLICABLE
    )


def test_apply_context_resolves_existing_ref():
    context = ApplyContext()

    reference = ExistingRef(
        resource_type="sensor",
        database_id=17,
    )

    assert context.resolve(reference) == 17


def test_apply_context_resolves_registered_planned_ref():
    context = ApplyContext()

    context.register(
        plan_id="sensors[0]",
        resource_type="sensor",
        database_id=52,
    )

    reference = PlannedRef(
        resource_type="sensor",
        plan_id="sensors[0]",
    )

    assert context.resolve(reference) == 52


def test_apply_context_rejects_unresolved_planned_ref():
    context = ApplyContext()

    reference = PlannedRef(
        resource_type="sensor",
        plan_id="sensors[0]",
    )

    with pytest.raises(ApplyError) as exc_info:
        context.resolve(reference)

    assert (
        exc_info.value.code
        == ApplyErrorCode.UNRESOLVED_PLANNED_REF
    )


def test_apply_context_rejects_planned_ref_with_wrong_resource_type():
    context = ApplyContext()

    context.register(
        plan_id="sensors[0]",
        resource_type="sensor",
        database_id=52,
    )

    reference = PlannedRef(
        resource_type="deployment",
        plan_id="sensors[0]",
    )

    with pytest.raises(ApplyError) as exc_info:
        context.resolve(reference)

    assert (
        exc_info.value.code
        == ApplyErrorCode.UNRESOLVED_PLANNED_REF
    )


def test_apply_context_rejects_duplicate_plan_id_registration():
    context = ApplyContext()

    context.register(
        plan_id="sensors[0]",
        resource_type="sensor",
        database_id=52,
    )

    with pytest.raises(
        ValueError,
        match="plan_id already registered",
    ):
        context.register(
            plan_id="sensors[0]",
            resource_type="sensor",
            database_id=53,
        )


@pytest.mark.parametrize(
    "database_id",
    [0, -1],
)
def test_apply_context_rejects_non_positive_database_id(
    database_id,
):
    context = ApplyContext()

    with pytest.raises(
        ValueError,
        match="database_id must be positive",
    ):
        context.register(
            plan_id="sensors[0]",
            resource_type="sensor",
            database_id=database_id,
        )


def test_apply_result_success_state():
    result = ApplyResult(
        status=ApplyStatus.SUCCESS,
        metadata_status=ApplyStageStatus.COMMITTED,
        raw_status=ApplyStageStatus.COMMITTED,
    )

    assert result.status == ApplyStatus.SUCCESS
    assert result.metadata_status == ApplyStageStatus.COMMITTED
    assert result.raw_status == ApplyStageStatus.COMMITTED
    assert result.items == ()


def test_apply_result_failed_state():
    result = ApplyResult(
        status=ApplyStatus.FAILED,
        metadata_status=ApplyStageStatus.FAILED,
        raw_status=ApplyStageStatus.NOT_REQUIRED,
    )

    assert result.status == ApplyStatus.FAILED
    assert result.metadata_status == ApplyStageStatus.FAILED
    assert result.raw_status == ApplyStageStatus.NOT_REQUIRED


def test_apply_result_partial_state():
    result = ApplyResult(
        status=ApplyStatus.PARTIAL,
        metadata_status=ApplyStageStatus.COMMITTED,
        raw_status=ApplyStageStatus.FAILED,
    )

    assert result.status == ApplyStatus.PARTIAL
    assert result.metadata_status == ApplyStageStatus.COMMITTED
    assert result.raw_status == ApplyStageStatus.FAILED


def test_apply_result_metadata_only_success():
    result = ApplyResult(
        status=ApplyStatus.SUCCESS,
        metadata_status=ApplyStageStatus.COMMITTED,
        raw_status=ApplyStageStatus.NOT_REQUIRED,
    )

    assert result.status == ApplyStatus.SUCCESS


def test_apply_result_empty_success():
    result = ApplyResult(
        status=ApplyStatus.SUCCESS,
        metadata_status=ApplyStageStatus.NOT_REQUIRED,
        raw_status=ApplyStageStatus.NOT_REQUIRED,
    )

    assert result.status == ApplyStatus.SUCCESS


def test_apply_item_result_records_persisted_identity():
    item = ApplyItemResult(
        plan_id="sensors[0]",
        resource_type="sensor",
        action=PlanAction.CREATE,
        database_id=52,
    )

    assert item.plan_id == "sensors[0]"
    assert item.resource_type == "sensor"
    assert item.action == PlanAction.CREATE
    assert item.database_id == 52


@pytest.mark.parametrize(
    "database_id",
    [0, -1],
)
def test_apply_item_result_rejects_non_positive_database_id(
    database_id,
):
    with pytest.raises(
        ValueError,
        match="database_id must be positive",
    ):
        ApplyItemResult(
            plan_id="sensors[0]",
            resource_type="sensor",
            action=PlanAction.CREATE,
            database_id=database_id,
        )



@pytest.mark.parametrize(
    (
        "status",
        "metadata_status",
        "raw_status",
    ),
    [
        (
            ApplyStatus.SUCCESS,
            ApplyStageStatus.FAILED,
            ApplyStageStatus.COMMITTED,
        ),
        (
            ApplyStatus.SUCCESS,
            ApplyStageStatus.COMMITTED,
            ApplyStageStatus.FAILED,
        ),
        (
            ApplyStatus.FAILED,
            ApplyStageStatus.COMMITTED,
            ApplyStageStatus.NOT_REQUIRED,
        ),
        (
            ApplyStatus.FAILED,
            ApplyStageStatus.NOT_REQUIRED,
            ApplyStageStatus.COMMITTED,
        ),
        (
            ApplyStatus.PARTIAL,
            ApplyStageStatus.NOT_REQUIRED,
            ApplyStageStatus.FAILED,
        ),
        (
            ApplyStatus.PARTIAL,
            ApplyStageStatus.COMMITTED,
            ApplyStageStatus.NOT_REQUIRED,
        ),
        (
            ApplyStatus.PARTIAL,
            ApplyStageStatus.COMMITTED,
            ApplyStageStatus.COMMITTED,
        ),
    ],
)
def test_apply_result_rejects_invalid_stage_state(
    status,
    metadata_status,
    raw_status,
):
    with pytest.raises(ValueError):
        ApplyResult(
            status=status,
            metadata_status=metadata_status,
            raw_status=raw_status,
        )


def test_apply_result_raw_only_success():
    result = ApplyResult(
        status=ApplyStatus.SUCCESS,
        metadata_status=ApplyStageStatus.NOT_REQUIRED,
        raw_status=ApplyStageStatus.COMMITTED,
    )

    assert result.status == ApplyStatus.SUCCESS

