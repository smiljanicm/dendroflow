from datetime import datetime, timezone

from dendroflow.configuration.plan import (
    ExistingRef,
    FieldChange,
    PlanAction,
    PlanErrorCode,
    ResolvedDeploymentValues,
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSensorValues,
)
from dendroflow.configuration.resolution.consistency import (
    collect_plan_consistency_errors,
)


def test_empty_plan_has_no_consistency_errors():
    plan = ResolvedPlan()

    errors = collect_plan_consistency_errors(plan)

    assert errors == ()


def test_clean_plan_has_no_consistency_errors():
    sensor_item = ResolvedPlanItem(
        plan_id="sensors[0]",
        resource_type="sensor",
        action=PlanAction.REUSE,
        database_id=17,
        values=ResolvedSensorValues(
            sensor_model=ExistingRef(
                resource_type="sensor_model",
                database_id=3,
            ),
            serial_number="SENSOR123",
            description=None,
        ),
        source_path="sensors[0]",
    )

    plan = ResolvedPlan(
        metadata_items=(sensor_item,),
    )

    errors = collect_plan_consistency_errors(plan)

    assert errors == ()


# Red - green tests


def _sensor_update_item(
    plan_id: str,
    database_id: int,
    serial_number: str,
) -> ResolvedPlanItem:
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="sensor",
        action=PlanAction.UPDATE,
        database_id=database_id,
        values=ResolvedSensorValues(
            sensor_model=ExistingRef(
                resource_type="sensor_model",
                database_id=3,
            ),
            serial_number=serial_number,
            description=None,
        ),
        changes=(
            FieldChange(
                field="serial_number",
                before="OLD",
                after=serial_number,
                identity_change=True,
            ),
        ),
        source_path=plan_id,
    )


# Failing initially - clean after update
def test_duplicate_sensor_update_target_conflicts():
    first = _sensor_update_item(
        "updates.sensors[0]",
        17,
        "NEW_A",
    )
    second = _sensor_update_item(
        "updates.sensors[1]",
        17,
        "NEW_B",
    )

    plan = ResolvedPlan(
        metadata_items=(first, second),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1

    error = errors[0]

    assert error.code == PlanErrorCode.CONFLICT
    assert error.resource_type == "sensor"


# Clean test
def test_different_sensor_update_targets_are_consistent():
    first = _sensor_update_item(
        "updates.sensors[0]",
        17,
        "NEW_A",
    )
    second = _sensor_update_item(
        "updates.sensors[1]",
        18,
        "NEW_B",
    )

    plan = ResolvedPlan(
        metadata_items=(first, second),
    )

    errors = collect_plan_consistency_errors(plan)

    assert errors == ()


# Clean test
def test_reuse_and_update_same_sensor_are_consistent():
    reuse = ResolvedPlanItem(
        plan_id="sensors[0]",
        resource_type="sensor",
        action=PlanAction.REUSE,
        database_id=17,
        values=ResolvedSensorValues(
            sensor_model=ExistingRef(
                resource_type="sensor_model",
                database_id=3,
            ),
            serial_number="OLD",
            description=None,
        ),
        source_path="sensors[0]",
    )

    update = _sensor_update_item(
        "updates.sensors[0]",
        17,
        "NEW",
    )

    plan = ResolvedPlan(
        metadata_items=(reuse, update),
    )

    errors = collect_plan_consistency_errors(plan)

    assert errors == ()


# Clean test
def test_duplicate_deployment_update_target_conflicts():
    first = ResolvedPlanItem(
        plan_id="updates.deployments[0]",
        resource_type="deployment",
        action=PlanAction.UPDATE,
        database_id=41,
        values=ResolvedDeploymentValues(
            sensor=ExistingRef(
                resource_type="sensor",
                database_id=11,
            ),
            location=ExistingRef(
                resource_type="location",
                database_id=21,
            ),
            variable=ExistingRef(
                resource_type="variable",
                database_id=31,
            ),
            valid_from=datetime(
                2025,
                4,
                1,
                tzinfo=timezone.utc,
            ),
            valid_to=None,
        ),
        changes=(
            FieldChange(
                field="valid_to",
                before=None,
                after=datetime(
                    2025,
                    5,
                    1,
                    tzinfo=timezone.utc,
                ),
                identity_change=False,
            ),
        ),
        source_path="updates.deployments[0]",
    )

    second = ResolvedPlanItem(
        plan_id="updates.deployments[1]",
        resource_type="deployment",
        action=PlanAction.UPDATE,
        database_id=41,
        values=ResolvedDeploymentValues(
            sensor=ExistingRef(
                resource_type="sensor",
                database_id=11,
            ),
            location=ExistingRef(
                resource_type="location",
                database_id=21,
            ),
            variable=ExistingRef(
                resource_type="variable",
                database_id=31,
            ),
            valid_from=datetime(
                2025,
                4,
                1,
                tzinfo=timezone.utc,
            ),
            valid_to=datetime(
                2025,
                6,
                1,
                tzinfo=timezone.utc,
            ),
        ),
        changes=(
            FieldChange(
                field="valid_to",
                before=None,
                after=datetime(
                    2025,
                    6,
                    1,
                    tzinfo=timezone.utc,
                ),
                identity_change=False,
            ),
        ),
        source_path="updates.deployments[1]",
    )

    plan = ResolvedPlan(
        metadata_items=(first, second),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "deployment"
    assert errors[0].source_path == (
        "updates.deployments[1]"
    )


