import pytest

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


def test_existing_ref_requires_positive_database_id():
    with pytest.raises(
        ValueError,
        match="database_id must be greater than zero",
    ):
        ExistingRef(
            resource_type="sensor",
            database_id=0,
        )


def test_planned_ref_identifies_future_resource():
    ref = PlannedRef(
        resource_type="sensor_model",
        plan_id="sensor_models[0]",
    )

    assert ref.plan_id == "sensor_models[0]"


def test_create_plan_item_has_no_database_id():
    item = ResolvedPlanItem(
        plan_id="sensors[0]",
        resource_type="sensor",
        action=PlanAction.CREATE,
        values=ResolvedSensorValues(
            serial_number="123456",
            sensor_model=PlannedRef(
                resource_type="sensor_model",
                plan_id="sensor_models[0]",
            ),
        ),
    )

    assert item.database_id is None


def test_reuse_plan_item_requires_database_id():
    with pytest.raises(
        ValueError,
        match="REUSE plan item must have database_id",
    ):
        ResolvedPlanItem(
            plan_id="variables[0]",
            resource_type="variable",
            action=PlanAction.REUSE,
            values=object(),
        )


def test_update_plan_item_requires_changes():
    with pytest.raises(
        ValueError,
        match="UPDATE plan item must contain at least one change",
    ):
        ResolvedPlanItem(
            plan_id="updates.sensors[0]",
            resource_type="sensor",
            action=PlanAction.UPDATE,
            database_id=7,
            values=object(),
        )


def test_identity_change_requires_confirmation():
    item = ResolvedPlanItem(
        plan_id="updates.sensors[0]",
        resource_type="sensor",
        action=PlanAction.UPDATE,
        database_id=7,
        values=object(),
        changes=(
            FieldChange(
                field="serial_number",
                before="OLD123",
                after="NEW123",
                identity_change=True,
            ),
        ),
    )

    assert item.requires_confirmation


def test_plan_cannot_apply_with_errors():
    plan = ResolvedPlan(
        errors=(
            PlanError(
                code=PlanErrorCode.AMBIGUOUS,
                resource_type="deployment",
                source_path="references.deployments.main",
                message="multiple deployments matched",
                candidate_ids=(1, 2),
            ),
        )
    )

    assert not plan.can_apply


def test_plan_counts_actions_across_databases():
    plan = ResolvedPlan(
        metadata_items=(
            ResolvedPlanItem(
                plan_id="variables[0]",
                resource_type="variable",
                action=PlanAction.REUSE,
                database_id=1,
                values=object(),
            ),
            ResolvedPlanItem(
                plan_id="sensors[0]",
                resource_type="sensor",
                action=PlanAction.CREATE,
                values=object(),
            ),
        ),
        raw_items=(
            ResolvedPlanItem(
                plan_id="files[0]",
                resource_type="file",
                action=PlanAction.CREATE,
                values=object(),
            ),
        ),
    )

    assert plan.count(PlanAction.CREATE) == 2
    assert plan.count(PlanAction.REUSE) == 1


