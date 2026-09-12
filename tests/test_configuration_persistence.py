import pytest

from dendroflow.configuration.persistence.context import (
    ApplyContext,
)
from dendroflow.configuration.persistence.models import (
    ApplyError,
    ApplyErrorCode,
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


