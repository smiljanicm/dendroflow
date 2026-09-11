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
    ExistingDeploymentState,
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


## Failing initially - clean after update
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


## Clean test
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


## Clean test
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


## Clean test
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


def _sensor_create_item(
    plan_id: str,
    serial_number: str,
    sensor_model_id: int = 3,
) -> ResolvedPlanItem:
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="sensor",
        action=PlanAction.CREATE,
        values=ResolvedSensorValues(
            sensor_model=ExistingRef(
                resource_type="sensor_model",
                database_id=sensor_model_id,
            ),
            serial_number=serial_number,
            description=None,
        ),
        source_path=plan_id,
    )


## Failing initially - clean after update
def test_sensor_updates_with_same_final_identity_conflict():
    first = _sensor_update_item(
        "updates.sensors[0]",
        17,
        "NEW123",
    )
    second = _sensor_update_item(
        "updates.sensors[1]",
        18,
        "NEW123",
    )

    plan = ResolvedPlan(
        metadata_items=(first, second),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1

    error = errors[0]

    assert error.code == PlanErrorCode.CONFLICT
    assert error.resource_type == "sensor"
    assert error.source_path == "updates.sensors[1]"


## Clean test
def test_sensor_updates_with_different_final_identities_are_consistent():
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


## Failing initially - clean after update
def test_sensor_create_and_update_with_same_final_identity_conflict():
    created = _sensor_create_item(
        "sensors[0]",
        "NEW123",
    )
    updated = _sensor_update_item(
        "updates.sensors[0]",
        17,
        "NEW123",
    )

    plan = ResolvedPlan(
        metadata_items=(created, updated),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1

    error = errors[0]

    assert error.code == PlanErrorCode.CONFLICT
    assert error.resource_type == "sensor"
    assert error.source_path == "updates.sensors[0]"


## Clean test
def test_same_sensor_serial_under_different_models_is_consistent():
    first = _sensor_create_item(
        "sensors[0]",
        "NEW123",
        sensor_model_id=3,
    )
    second = _sensor_create_item(
        "sensors[1]",
        "NEW123",
        sensor_model_id=4,
    )

    plan = ResolvedPlan(
        metadata_items=(first, second),
    )

    errors = collect_plan_consistency_errors(plan)

    assert errors == ()


## Clean test
def test_sensor_creates_with_same_final_identity_conflict():
    first = _sensor_create_item(
        "sensors[0]",
        "NEW123",
    )
    second = _sensor_create_item(
        "sensors[1]",
        "NEW123",
    )

    plan = ResolvedPlan(
        metadata_items=(first, second),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "sensor"
    assert errors[0].source_path == "sensors[1]"


# Deployment temporal consistency


def _deployment_create_item(
    plan_id: str,
    *,
    sensor_id: int = 11,
    location_id: int = 21,
    variable_id: int = 31,
    valid_from: datetime,
    valid_to: datetime | None,
) -> ResolvedPlanItem:
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="deployment",
        action=PlanAction.CREATE,
        values=ResolvedDeploymentValues(
            sensor=ExistingRef(
                resource_type="sensor",
                database_id=sensor_id,
            ),
            location=ExistingRef(
                resource_type="location",
                database_id=location_id,
            ),
            variable=ExistingRef(
                resource_type="variable",
                database_id=variable_id,
            ),
            valid_from=valid_from,
            valid_to=valid_to,
        ),
        source_path=plan_id,
    )


## Failing initially - clean after update
def test_overlapping_deployment_creates_conflict():
    first = _deployment_create_item(
        "deployments[0]",
        valid_from=datetime(
            2025, 1, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 3, 1, tzinfo=timezone.utc
        ),
    )
    second = _deployment_create_item(
        "deployments[1]",
        location_id=22,
        valid_from=datetime(
            2025, 2, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 4, 1, tzinfo=timezone.utc
        ),
    )

    plan = ResolvedPlan(
        metadata_items=(first, second),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "deployment"
    assert errors[0].source_path == "deployments[1]"


## Clean test
def test_adjacent_deployment_creates_are_consistent():
    first = _deployment_create_item(
        "deployments[0]",
        valid_from=datetime(
            2025, 1, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 3, 1, tzinfo=timezone.utc
        ),
    )
    second = _deployment_create_item(
        "deployments[1]",
        location_id=22,
        valid_from=datetime(
            2025, 3, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 4, 1, tzinfo=timezone.utc
        ),
    )

    plan = ResolvedPlan(
        metadata_items=(first, second),
    )

    errors = collect_plan_consistency_errors(plan)

    assert errors == ()


## Clean test
def test_overlapping_deployments_for_different_variables_are_consistent():
    first = _deployment_create_item(
        "deployments[0]",
        variable_id=31,
        valid_from=datetime(
            2025, 1, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 3, 1, tzinfo=timezone.utc
        ),
    )
    second = _deployment_create_item(
        "deployments[1]",
        variable_id=32,
        valid_from=datetime(
            2025, 2, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 4, 1, tzinfo=timezone.utc
        ),
    )

    plan = ResolvedPlan(
        metadata_items=(first, second),
    )

    errors = collect_plan_consistency_errors(plan)

    assert errors == ()


## Clean test
def test_open_ended_deployment_create_overlaps_later_create():
    first = _deployment_create_item(
        "deployments[0]",
        valid_from=datetime(
            2025, 1, 1, tzinfo=timezone.utc
        ),
        valid_to=None,
    )
    second = _deployment_create_item(
        "deployments[1]",
        location_id=22,
        valid_from=datetime(
            2025, 6, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 7, 1, tzinfo=timezone.utc
        ),
    )

    plan = ResolvedPlan(
        metadata_items=(first, second),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "deployment"
    assert errors[0].source_path == "deployments[1]"


def _deployment_update_item(
    plan_id: str,
    database_id: int,
    *,
    sensor_id: int = 11,
    location_id: int = 21,
    variable_id: int = 31,
    valid_from: datetime,
    valid_to: datetime | None,
) -> ResolvedPlanItem:
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="deployment",
        action=PlanAction.UPDATE,
        database_id=database_id,
        values=ResolvedDeploymentValues(
            sensor=ExistingRef(
                resource_type="sensor",
                database_id=sensor_id,
            ),
            location=ExistingRef(
                resource_type="location",
                database_id=location_id,
            ),
            variable=ExistingRef(
                resource_type="variable",
                database_id=variable_id,
            ),
            valid_from=valid_from,
            valid_to=valid_to,
        ),
        changes=(
            FieldChange(
                field="valid_from",
                before=datetime(
                    2025, 1, 1, tzinfo=timezone.utc
                ),
                after=valid_from,
                identity_change=True,
            ),
        ),
        source_path=plan_id,
    )


## Failing initially - clean after update
def test_deployment_create_and_update_overlap_conflict():
    created = _deployment_create_item(
        "deployments[0]",
        location_id=22,
        valid_from=datetime(
            2025, 3, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 5, 1, tzinfo=timezone.utc
        ),
    )

    updated = _deployment_update_item(
        "updates.deployments[0]",
        41,
        valid_from=datetime(
            2025, 2, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 4, 1, tzinfo=timezone.utc
        ),
    )

    plan = ResolvedPlan(
        metadata_items=(created, updated),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "deployment"
    assert errors[0].source_path == (
        "updates.deployments[0]"
    )


## Clean test
def test_deployment_create_and_update_adjacent_are_consistent():
    created = _deployment_create_item(
        "deployments[0]",
        valid_from=datetime(
            2025, 1, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 3, 1, tzinfo=timezone.utc
        ),
    )

    updated = _deployment_update_item(
        "updates.deployments[0]",
        41,
        location_id=22,
        valid_from=datetime(
            2025, 3, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 5, 1, tzinfo=timezone.utc
        ),
    )

    plan = ResolvedPlan(
        metadata_items=(created, updated),
    )

    errors = collect_plan_consistency_errors(plan)

    assert errors == ()


## Clean test
def test_deployment_updates_with_overlapping_final_intervals_conflict():
    first = _deployment_update_item(
        "updates.deployments[0]",
        41,
        valid_from=datetime(
            2025, 1, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 3, 1, tzinfo=timezone.utc
        ),
    )

    second = _deployment_update_item(
        "updates.deployments[1]",
        42,
        location_id=22,
        valid_from=datetime(
            2025, 2, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 4, 1, tzinfo=timezone.utc
        ),
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


## Clean test
def test_deployment_updates_with_adjacent_final_intervals_are_consistent():
    first = _deployment_update_item(
        "updates.deployments[0]",
        41,
        valid_from=datetime(
            2025, 1, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 3, 1, tzinfo=timezone.utc
        ),
    )

    second = _deployment_update_item(
        "updates.deployments[1]",
        42,
        location_id=22,
        valid_from=datetime(
            2025, 3, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 4, 1, tzinfo=timezone.utc
        ),
    )

    plan = ResolvedPlan(
        metadata_items=(first, second),
    )

    errors = collect_plan_consistency_errors(plan)

    assert errors == ()


## Failing initially - clean after update
def test_deployment_create_overlapping_existing_history_conflicts():
    created = _deployment_create_item(
        "deployments[0]",
        location_id=22,
        valid_from=datetime(
            2025, 3, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 5, 1, tzinfo=timezone.utc
        ),
    )

    existing = ExistingDeploymentState(
        deployment_id=41,
        sensor_id=11,
        variable_id=31,
        valid_from=datetime(
            2025, 1, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 4, 1, tzinfo=timezone.utc
        ),
    )

    plan = ResolvedPlan(
        metadata_items=(created,),
    )

    errors = collect_plan_consistency_errors(
        plan,
        existing_deployments=(existing,),
    )

    assert len(errors) == 1

    error = errors[0]

    assert error.code == PlanErrorCode.CONFLICT
    assert error.resource_type == "deployment"
    assert error.source_path == "deployments[0]"


## Clean test
def test_deployment_create_adjacent_to_existing_history_is_consistent():
    created = _deployment_create_item(
        "deployments[0]",
        location_id=22,
        valid_from=datetime(
            2025, 4, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 5, 1, tzinfo=timezone.utc
        ),
    )

    existing = ExistingDeploymentState(
        deployment_id=41,
        sensor_id=11,
        variable_id=31,
        valid_from=datetime(
            2025, 1, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 4, 1, tzinfo=timezone.utc
        ),
    )

    plan = ResolvedPlan(
        metadata_items=(created,),
    )

    errors = collect_plan_consistency_errors(
        plan,
        existing_deployments=(existing,),
    )

    assert errors == ()


def test_deployment_update_overlapping_other_existing_history_conflicts():
    updated = _deployment_update_item(
        "updates.deployments[0]",
        41,
        valid_from=datetime(
            2025, 3, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 5, 1, tzinfo=timezone.utc
        ),
    )

    existing = ExistingDeploymentState(
        deployment_id=42,
        sensor_id=11,
        variable_id=31,
        valid_from=datetime(
            2025, 1, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 4, 1, tzinfo=timezone.utc
        ),
    )

    plan = ResolvedPlan(
        metadata_items=(updated,),
    )

    errors = collect_plan_consistency_errors(
        plan,
        existing_deployments=(existing,),
    )

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "deployment"
    assert errors[0].source_path == (
        "updates.deployments[0]"
    )


def test_deployment_update_ignores_own_existing_history():
    updated = _deployment_update_item(
        "updates.deployments[0]",
        41,
        valid_from=datetime(
            2025, 3, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 5, 1, tzinfo=timezone.utc
        ),
    )

    existing = ExistingDeploymentState(
        deployment_id=41,
        sensor_id=11,
        variable_id=31,
        valid_from=datetime(
            2025, 1, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 4, 1, tzinfo=timezone.utc
        ),
    )

    plan = ResolvedPlan(
        metadata_items=(updated,),
    )

    errors = collect_plan_consistency_errors(
        plan,
        existing_deployments=(existing,),
    )

    assert errors == ()


def test_deployment_history_with_different_variable_is_consistent():
    created = _deployment_create_item(
        "deployments[0]",
        valid_from=datetime(
            2025, 3, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 5, 1, tzinfo=timezone.utc
        ),
    )

    existing = ExistingDeploymentState(
        deployment_id=41,
        sensor_id=11,
        variable_id=32,
        valid_from=datetime(
            2025, 1, 1, tzinfo=timezone.utc
        ),
        valid_to=datetime(
            2025, 4, 1, tzinfo=timezone.utc
        ),
    )

    plan = ResolvedPlan(
        metadata_items=(created,),
    )

    errors = collect_plan_consistency_errors(
        plan,
        existing_deployments=(existing,),
    )

    assert errors == ()


