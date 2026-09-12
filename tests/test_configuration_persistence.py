import pytest

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

