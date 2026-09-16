from dataclasses import replace
from datetime import datetime, timezone

import pytest

from dendroflow.configuration.plan import (
    ExistingRef,
    FieldChange,
    PlanAction,
    PlanErrorCode,
    PlannedRef,
    ResolvedDeploymentValues,
    ResolvedFileValues,
    ResolvedInterfaceValues,
    ResolvedLocationTypeValues,
    ResolvedLocationValues,
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSensorModelValues,
    ResolvedSensorTypeValues,
    ResolvedSensorValues,
    ResolvedSiteValues,
    ResolvedVariableValues,
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


def test_deployment_planned_sensor_reference_is_consistent():
    sensor = _sensor_create_item(
        "sensors[0]",
        "NEW123",
    )

    deployment = ResolvedPlanItem(
        plan_id="deployments[0]",
        resource_type="deployment",
        action=PlanAction.CREATE,
        values=ResolvedDeploymentValues(
            sensor=PlannedRef(
                resource_type="sensor",
                plan_id="sensors[0]",
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
                2025, 1, 1, tzinfo=timezone.utc
            ),
            valid_to=None,
        ),
        source_path="deployments[0]",
    )

    plan = ResolvedPlan(
        metadata_items=(
            sensor,
            deployment,
        ),
    )

    errors = collect_plan_consistency_errors(plan)

    assert errors == ()


def test_dangling_deployment_planned_sensor_reference_conflicts():
    deployment = ResolvedPlanItem(
        plan_id="deployments[0]",
        resource_type="deployment",
        action=PlanAction.CREATE,
        values=ResolvedDeploymentValues(
            sensor=PlannedRef(
                resource_type="sensor",
                plan_id="sensors[99]",
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
                2025, 1, 1, tzinfo=timezone.utc
            ),
            valid_to=None,
        ),
        source_path="deployments[0]",
    )

    plan = ResolvedPlan(
        metadata_items=(deployment,),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1

    error = errors[0]

    assert error.code == PlanErrorCode.CONFLICT
    assert error.resource_type == "deployment"
    assert error.source_path == "deployments[0]"


def test_planned_reference_with_wrong_resource_type_conflicts():
    location = ResolvedPlanItem(
        plan_id="locations[0]",
        resource_type="location",
        action=PlanAction.CREATE,
        values=...,
        source_path="locations[0]",
    )

    deployment = ResolvedPlanItem(
        plan_id="deployments[0]",
        resource_type="deployment",
        action=PlanAction.CREATE,
        values=ResolvedDeploymentValues(
            sensor=PlannedRef(
                resource_type="sensor",
                plan_id="locations[0]",
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
                2025, 1, 1, tzinfo=timezone.utc
            ),
            valid_to=None,
        ),
        source_path="deployments[0]",
    )

    plan = ResolvedPlan(
        metadata_items=(
            location,
            deployment,
        ),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "deployment"
    assert errors[0].source_path == "deployments[0]"


def test_interface_planned_file_reference_is_consistent():
    file_item = ResolvedPlanItem(
        plan_id="files[0]",
        resource_type="file",
        action=PlanAction.CREATE,
        values=ResolvedFileValues(
            filepath="tests/data/example.csv",
            timestamp_timezone="Etc/GMT-1",
            timestamp_format="%Y-%m-%d %H:%M:%S",
            reader_config={
                "reader": "csv",
                "options": {},
            },
        ),
        source_path="files[0]",
    )

    interface = ResolvedPlanItem(
        plan_id="files[0].interfaces[0]",
        resource_type="interface",
        action=PlanAction.CREATE,
        values=ResolvedInterfaceValues(
            file=PlannedRef(
                resource_type="file",
                plan_id="files[0]",
            ),
            deployment=ExistingRef(
                resource_type="deployment",
                database_id=41,
            ),
            values_column="value",
            timestamp_column="timestamp",
            unit="cm",
        ),
        source_path="files[0].interfaces[0]",
    )

    plan = ResolvedPlan(
        raw_items=(
            file_item,
            interface,
        ),
    )

    errors = collect_plan_consistency_errors(plan)

    assert errors == ()


def test_dangling_interface_planned_file_reference_conflicts():
    interface = ResolvedPlanItem(
        plan_id="files[0].interfaces[0]",
        resource_type="interface",
        action=PlanAction.CREATE,
        values=ResolvedInterfaceValues(
            file=PlannedRef(
                resource_type="file",
                plan_id="files[99]",
            ),
            deployment=ExistingRef(
                resource_type="deployment",
                database_id=41,
            ),
            values_column="value",
            timestamp_column="timestamp",
            unit="cm",
        ),
        source_path="files[0].interfaces[0]",
    )

    plan = ResolvedPlan(
        raw_items=(interface,),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1

    error = errors[0]

    assert error.code == PlanErrorCode.CONFLICT
    assert error.resource_type == "interface"
    assert error.source_path == "files[0].interfaces[0]"


def test_interface_planned_deployment_reference_is_consistent():
    deployment = _deployment_create_item(
        "deployments[0]",
        valid_from=datetime(
            2025, 1, 1, tzinfo=timezone.utc
        ),
        valid_to=None,
    )

    file_item = ResolvedPlanItem(
        plan_id="files[0]",
        resource_type="file",
        action=PlanAction.CREATE,
        values=ResolvedFileValues(
            filepath="tests/data/example.csv",
            timestamp_timezone="Etc/GMT-1",
            timestamp_format="%Y-%m-%d %H:%M:%S",
            reader_config={
                "reader": "csv",
                "options": {},
            },
        ),
        source_path="files[0]",
    )

    interface = ResolvedPlanItem(
        plan_id="files[0].interfaces[0]",
        resource_type="interface",
        action=PlanAction.CREATE,
        values=ResolvedInterfaceValues(
            file=PlannedRef(
                resource_type="file",
                plan_id="files[0]",
            ),
            deployment=PlannedRef(
                resource_type="deployment",
                plan_id="deployments[0]",
            ),
            values_column="value",
            timestamp_column="timestamp",
            unit="cm",
        ),
        source_path="files[0].interfaces[0]",
    )

    plan = ResolvedPlan(
        metadata_items=(deployment,),
        raw_items=(
            file_item,
            interface,
        ),
    )

    errors = collect_plan_consistency_errors(plan)

    assert errors == ()


def test_dangling_interface_planned_deployment_reference_conflicts():
    file_item = ResolvedPlanItem(
        plan_id="files[0]",
        resource_type="file",
        action=PlanAction.CREATE,
        values=ResolvedFileValues(
            filepath="tests/data/example.csv",
            timestamp_timezone="Etc/GMT-1",
            timestamp_format="%Y-%m-%d %H:%M:%S",
            reader_config={
                "reader": "csv",
                "options": {},
            },
        ),
        source_path="files[0]",
    )

    interface = ResolvedPlanItem(
        plan_id="files[0].interfaces[0]",
        resource_type="interface",
        action=PlanAction.CREATE,
        values=ResolvedInterfaceValues(
            file=PlannedRef(
                resource_type="file",
                plan_id="files[0]",
            ),
            deployment=PlannedRef(
                resource_type="deployment",
                plan_id="deployments[99]",
            ),
            values_column="value",
            timestamp_column="timestamp",
            unit="cm",
        ),
        source_path="files[0].interfaces[0]",
    )

    plan = ResolvedPlan(
        raw_items=(
            file_item,
            interface,
        ),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "interface"
    assert errors[0].source_path == (
        "files[0].interfaces[0]"
    )


def test_interface_planned_reference_with_wrong_resource_type_conflicts():
    deployment = _deployment_create_item(
        "deployments[0]",
        valid_from=datetime(
            2025, 1, 1, tzinfo=timezone.utc
        ),
        valid_to=None,
    )

    interface = ResolvedPlanItem(
        plan_id="files[0].interfaces[0]",
        resource_type="interface",
        action=PlanAction.CREATE,
        values=ResolvedInterfaceValues(
            file=PlannedRef(
                resource_type="file",
                plan_id="deployments[0]",
            ),
            deployment=ExistingRef(
                resource_type="deployment",
                database_id=41,
            ),
            values_column="value",
            timestamp_column="timestamp",
            unit="cm",
        ),
        source_path="files[0].interfaces[0]",
    )

    plan = ResolvedPlan(
        metadata_items=(deployment,),
        raw_items=(interface,),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "interface"
    assert errors[0].source_path == (
        "files[0].interfaces[0]"
    )


def test_multiple_consistency_errors_accumulate():
    first_update = _sensor_update_item(
        "updates.sensors[0]",
        17,
        "NEW_A",
    )
    second_update = _sensor_update_item(
        "updates.sensors[1]",
        17,
        "NEW_B",
    )

    interface = ResolvedPlanItem(
        plan_id="files[0].interfaces[0]",
        resource_type="interface",
        action=PlanAction.CREATE,
        values=ResolvedInterfaceValues(
            file=PlannedRef(
                resource_type="file",
                plan_id="files[99]",
            ),
            deployment=ExistingRef(
                resource_type="deployment",
                database_id=41,
            ),
            values_column="value",
            timestamp_column="timestamp",
            unit="cm",
        ),
        source_path="files[0].interfaces[0]",
    )

    plan = ResolvedPlan(
        metadata_items=(
            first_update,
            second_update,
        ),
        raw_items=(interface,),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 2

    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].source_path == (
        "updates.sensors[1]"
    )

    assert errors[1].code == PlanErrorCode.CONFLICT
    assert errors[1].source_path == (
        "files[0].interfaces[0]"
    )


def test_consistency_errors_have_deterministic_rule_order():
    duplicate_first = _sensor_update_item(
        "updates.sensors[0]",
        17,
        "SERIAL_A",
    )
    duplicate_second = _sensor_update_item(
        "updates.sensors[1]",
        17,
        "SERIAL_B",
    )

    identity_first = _sensor_update_item(
        "updates.sensors[2]",
        18,
        "COLLISION",
    )
    identity_second = _sensor_update_item(
        "updates.sensors[3]",
        19,
        "COLLISION",
    )

    interface = ResolvedPlanItem(
        plan_id="files[0].interfaces[0]",
        resource_type="interface",
        action=PlanAction.CREATE,
        values=ResolvedInterfaceValues(
            file=PlannedRef(
                resource_type="file",
                plan_id="files[99]",
            ),
            deployment=ExistingRef(
                resource_type="deployment",
                database_id=41,
            ),
            values_column="value",
            timestamp_column="timestamp",
            unit="cm",
        ),
        source_path="files[0].interfaces[0]",
    )

    plan = ResolvedPlan(
        metadata_items=(
            duplicate_first,
            duplicate_second,
            identity_first,
            identity_second,
        ),
        raw_items=(interface,),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 3

    assert tuple(
        error.source_path
        for error in errors
    ) == (
        "updates.sensors[1]",
        "updates.sensors[3]",
        "files[0].interfaces[0]",
    )


def _site_identity_item(
    *,
    plan_id: str,
    action: PlanAction,
    site_code: str,
    database_id: int | None = None,
) -> ResolvedPlanItem:
    changes = ()

    if action == PlanAction.UPDATE:
        changes = (
            FieldChange(
                field="site_code",
                before="OLD",
                after=site_code,
                identity_change=True,
            ),
        )

    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="site",
        action=action,
        database_id=database_id,
        values=ResolvedSiteValues(
            site_code=site_code,
            name="Test site",
        ),
        changes=changes,
        source_path=plan_id,
    )


def _location_type_identity_item(
    *,
    plan_id: str,
    action: PlanAction,
    type_: str,
    database_id: int | None = None,
) -> ResolvedPlanItem:
    changes = ()

    if action == PlanAction.UPDATE:
        changes = (
            FieldChange(
                field="type",
                before="OLD",
                after=type_,
                identity_change=True,
            ),
        )

    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="location_type",
        action=action,
        database_id=database_id,
        values=ResolvedLocationTypeValues(
            type=type_,
        ),
        changes=changes,
        source_path=plan_id,
    )


def _sensor_type_identity_item(
    *,
    plan_id: str,
    action: PlanAction,
    type_: str,
    database_id: int | None = None,
) -> ResolvedPlanItem:
    changes = ()

    if action == PlanAction.UPDATE:
        changes = (
            FieldChange(
                field="type",
                before="OLD",
                after=type_,
                identity_change=True,
            ),
        )

    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="sensor_type",
        action=action,
        database_id=database_id,
        values=ResolvedSensorTypeValues(
            type=type_,
        ),
        changes=changes,
        source_path=plan_id,
    )


def _variable_identity_item(
    *,
    plan_id: str,
    action: PlanAction,
    variable: str,
    database_id: int | None = None,
) -> ResolvedPlanItem:
    changes = ()

    if action == PlanAction.UPDATE:
        changes = (
            FieldChange(
                field="variable",
                before="OLD",
                after=variable,
                identity_change=True,
            ),
        )

    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="variable",
        action=action,
        database_id=database_id,
        values=ResolvedVariableValues(
            variable=variable,
        ),
        changes=changes,
        source_path=plan_id,
    )


def test_site_updates_with_same_final_identity_conflict():
    first = _site_identity_item(
        plan_id="updates.sites[0]",
        action=PlanAction.UPDATE,
        database_id=11,
        site_code="SANDHAGEN",
    )
    second = _site_identity_item(
        plan_id="updates.sites[1]",
        action=PlanAction.UPDATE,
        database_id=12,
        site_code="SANDHAGEN",
    )

    plan = ResolvedPlan(
        metadata_items=(first, second),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "site"
    assert errors[0].source_path == "updates.sites[1]"


def test_location_type_create_and_update_identity_conflict():
    created = _location_type_identity_item(
        plan_id="location_types[0]",
        action=PlanAction.CREATE,
        type_="stem",
    )
    updated = _location_type_identity_item(
        plan_id="updates.location_types[0]",
        action=PlanAction.UPDATE,
        database_id=21,
        type_="stem",
    )

    plan = ResolvedPlan(
        metadata_items=(created, updated),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "location_type"
    assert errors[0].source_path == (
        "updates.location_types[0]"
    )


def test_sensor_type_update_conflicts_with_reused_identity():
    reused = _sensor_type_identity_item(
        plan_id="sensor_types[0]",
        action=PlanAction.REUSE,
        database_id=31,
        type_="pressure",
    )
    updated = _sensor_type_identity_item(
        plan_id="updates.sensor_types[0]",
        action=PlanAction.UPDATE,
        database_id=32,
        type_="pressure",
    )

    plan = ResolvedPlan(
        metadata_items=(reused, updated),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "sensor_type"
    assert errors[0].source_path == (
        "updates.sensor_types[0]"
    )


def test_same_sensor_type_reuse_and_update_are_consistent():
    reused = _sensor_type_identity_item(
        plan_id="sensor_types[0]",
        action=PlanAction.REUSE,
        database_id=31,
        type_="pressure",
    )
    updated = _sensor_type_identity_item(
        plan_id="updates.sensor_types[0]",
        action=PlanAction.UPDATE,
        database_id=31,
        type_="pressure",
    )

    plan = ResolvedPlan(
        metadata_items=(reused, updated),
    )

    errors = collect_plan_consistency_errors(plan)

    assert errors == ()


def test_variable_creates_with_same_final_identity_conflict():
    first = _variable_identity_item(
        plan_id="variables[0]",
        action=PlanAction.CREATE,
        variable="water_level",
    )
    second = _variable_identity_item(
        plan_id="variables[1]",
        action=PlanAction.CREATE,
        variable="water_level",
    )

    plan = ResolvedPlan(
        metadata_items=(first, second),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "variable"
    assert errors[0].source_path == "variables[1]"


def test_simple_resources_with_different_final_identities_are_consistent():
    items = (
        _site_identity_item(
            plan_id="updates.sites[0]",
            action=PlanAction.UPDATE,
            database_id=11,
            site_code="SITE_A",
        ),
        _site_identity_item(
            plan_id="updates.sites[1]",
            action=PlanAction.UPDATE,
            database_id=12,
            site_code="SITE_B",
        ),
        _variable_identity_item(
            plan_id="variables[0]",
            action=PlanAction.CREATE,
            variable="water_level",
        ),
        _variable_identity_item(
            plan_id="variables[1]",
            action=PlanAction.CREATE,
            variable="temperature",
        ),
    )

    plan = ResolvedPlan(
        metadata_items=items,
    )

    errors = collect_plan_consistency_errors(plan)

    assert errors == ()


def test_updated_resource_releases_reused_old_identity():
    reused = _sensor_type_identity_item(
        plan_id="sensor_types[0]",
        action=PlanAction.REUSE,
        database_id=31,
        type_="pressure",
    )
    updated = _sensor_type_identity_item(
        plan_id="updates.sensor_types[0]",
        action=PlanAction.UPDATE,
        database_id=31,
        type_="water_pressure",
    )
    created = _sensor_type_identity_item(
        plan_id="sensor_types[1]",
        action=PlanAction.CREATE,
        type_="pressure",
    )

    plan = ResolvedPlan(
        metadata_items=(reused, updated, created),
    )

    errors = collect_plan_consistency_errors(plan)

    assert errors == ()


def _sensor_model_identity_item(
    *,
    plan_id: str,
    action: PlanAction,
    manufacturer: str,
    model: str,
    database_id: int | None = None,
    sensor_type_id: int = 31,
) -> ResolvedPlanItem:
    changes = ()

    if action == PlanAction.UPDATE:
        changes = (
            FieldChange(
                field="manufacturer",
                before="OLD",
                after=manufacturer,
                identity_change=True,
            ),
        )

    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="sensor_model",
        action=action,
        database_id=database_id,
        values=ResolvedSensorModelValues(
            manufacturer=manufacturer,
            model=model,
            sensor_type=ExistingRef(
                resource_type="sensor_type",
                database_id=sensor_type_id,
            ),
        ),
        changes=changes,
        source_path=plan_id,
    )


def test_sensor_model_updates_with_same_final_identity_conflict():
    first = _sensor_model_identity_item(
        plan_id="updates.sensor_models[0]",
        action=PlanAction.UPDATE,
        database_id=51,
        manufacturer="Campbell Scientific",
        model="CS451",
    )
    second = _sensor_model_identity_item(
        plan_id="updates.sensor_models[1]",
        action=PlanAction.UPDATE,
        database_id=52,
        manufacturer="Campbell Scientific",
        model="CS451",
    )

    plan = ResolvedPlan(
        metadata_items=(first, second),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "sensor_model"
    assert errors[0].source_path == (
        "updates.sensor_models[1]"
    )


def test_sensor_model_create_and_update_identity_conflict():
    created = _sensor_model_identity_item(
        plan_id="sensor_models[0]",
        action=PlanAction.CREATE,
        manufacturer="Campbell Scientific",
        model="CS451",
    )
    updated = _sensor_model_identity_item(
        plan_id="updates.sensor_models[0]",
        action=PlanAction.UPDATE,
        database_id=52,
        manufacturer="Campbell Scientific",
        model="CS451",
    )

    plan = ResolvedPlan(
        metadata_items=(created, updated),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "sensor_model"


def test_sensor_models_with_same_model_but_different_manufacturer_are_consistent():
    first = _sensor_model_identity_item(
        plan_id="sensor_models[0]",
        action=PlanAction.CREATE,
        manufacturer="Campbell Scientific",
        model="CS451",
    )
    second = _sensor_model_identity_item(
        plan_id="sensor_models[1]",
        action=PlanAction.CREATE,
        manufacturer="Acme Sensors",
        model="CS451",
    )

    plan = ResolvedPlan(
        metadata_items=(first, second),
    )

    errors = collect_plan_consistency_errors(plan)

    assert errors == ()


def test_sensor_model_identity_ignores_sensor_type():
    first = _sensor_model_identity_item(
        plan_id="sensor_models[0]",
        action=PlanAction.CREATE,
        manufacturer="Campbell Scientific",
        model="CS451",
        sensor_type_id=31,
    )
    second = _sensor_model_identity_item(
        plan_id="sensor_models[1]",
        action=PlanAction.CREATE,
        manufacturer="Campbell Scientific",
        model="CS451",
        sensor_type_id=32,
    )

    plan = ResolvedPlan(
        metadata_items=(first, second),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "sensor_model"


def test_sensor_update_releases_reused_old_identity():
    reused = ResolvedPlanItem(
        plan_id="sensors[0]",
        resource_type="sensor",
        action=PlanAction.REUSE,
        database_id=17,
        values=ResolvedSensorValues(
            sensor_model=ExistingRef(
                resource_type="sensor_model",
                database_id=3,
            ),
            serial_number="OLD123",
            description=None,
        ),
        source_path="sensors[0]",
    )

    updated = ResolvedPlanItem(
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

    created = ResolvedPlanItem(
        plan_id="sensors[1]",
        resource_type="sensor",
        action=PlanAction.CREATE,
        values=ResolvedSensorValues(
            sensor_model=ExistingRef(
                resource_type="sensor_model",
                database_id=3,
            ),
            serial_number="OLD123",
            description=None,
        ),
        source_path="sensors[1]",
    )

    plan = ResolvedPlan(
        metadata_items=(reused, updated, created),
    )

    errors = collect_plan_consistency_errors(plan)

    assert errors == ()


def test_sensor_update_conflicts_with_other_reused_identity():
    reused = ResolvedPlanItem(
        plan_id="sensors[0]",
        resource_type="sensor",
        action=PlanAction.REUSE,
        database_id=18,
        values=ResolvedSensorValues(
            sensor_model=ExistingRef(
                resource_type="sensor_model",
                database_id=3,
            ),
            serial_number="TARGET123",
            description=None,
        ),
        source_path="sensors[0]",
    )

    updated = ResolvedPlanItem(
        plan_id="updates.sensors[0]",
        resource_type="sensor",
        action=PlanAction.UPDATE,
        database_id=17,
        values=ResolvedSensorValues(
            sensor_model=ExistingRef(
                resource_type="sensor_model",
                database_id=3,
            ),
            serial_number="TARGET123",
            description=None,
        ),
        changes=(
            FieldChange(
                field="serial_number",
                before="OLD123",
                after="TARGET123",
                identity_change=True,
            ),
        ),
        source_path="updates.sensors[0]",
    )

    plan = ResolvedPlan(
        metadata_items=(reused, updated),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "sensor"
    assert errors[0].source_path == "updates.sensors[0]"


def test_duplicate_site_update_target_conflicts():
    first = ResolvedPlanItem(
        plan_id="updates.sites[0]",
        resource_type="site",
        action=PlanAction.UPDATE,
        database_id=11,
        values=ResolvedSiteValues(
            site_code="SITE_A",
            name="First",
        ),
        changes=(
            FieldChange(
                field="name",
                before="Old",
                after="First",
                identity_change=False,
            ),
        ),
        source_path="updates.sites[0]",
    )

    second = ResolvedPlanItem(
        plan_id="updates.sites[1]",
        resource_type="site",
        action=PlanAction.UPDATE,
        database_id=11,
        values=ResolvedSiteValues(
            site_code="SITE_A",
            name="Second",
        ),
        changes=(
            FieldChange(
                field="name",
                before="Old",
                after="Second",
                identity_change=False,
            ),
        ),
        source_path="updates.sites[1]",
    )

    plan = ResolvedPlan(
        metadata_items=(first, second),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "site"
    assert errors[0].source_path == "updates.sites[1]"


def test_sensor_update_rejects_unresolved_planned_sensor_model():
    missing_model = PlannedRef(
        resource_type="sensor_model",
        plan_id="sensor_models[99]",
    )

    updated = ResolvedPlanItem(
        plan_id="updates.sensors[0]",
        resource_type="sensor",
        action=PlanAction.UPDATE,
        database_id=17,
        values=ResolvedSensorValues(
            sensor_model=missing_model,
            serial_number="SENSOR123",
            description=None,
        ),
        changes=(
            FieldChange(
                field="sensor_model",
                before=ExistingRef(
                    resource_type="sensor_model",
                    database_id=3,
                ),
                after=missing_model,
                identity_change=True,
            ),
        ),
        source_path="updates.sensors[0]",
    )

    plan = ResolvedPlan(
        metadata_items=(updated,),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "sensor"
    assert errors[0].source_path == "updates.sensors[0]"


def test_sensor_model_update_rejects_unresolved_planned_sensor_type():
    missing_type = PlannedRef(
        resource_type="sensor_type",
        plan_id="sensor_types[99]",
    )

    updated = ResolvedPlanItem(
        plan_id="updates.sensor_models[0]",
        resource_type="sensor_model",
        action=PlanAction.UPDATE,
        database_id=51,
        values=ResolvedSensorModelValues(
            manufacturer="Campbell Scientific",
            model="CS451",
            sensor_type=missing_type,
        ),
        changes=(
            FieldChange(
                field="sensor_type",
                before=ExistingRef(
                    resource_type="sensor_type",
                    database_id=31,
                ),
                after=missing_type,
                identity_change=False,
            ),
        ),
        source_path="updates.sensor_models[0]",
    )

    plan = ResolvedPlan(
        metadata_items=(updated,),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "sensor_model"
    assert errors[0].source_path == "updates.sensor_models[0]"


def test_location_update_rejects_unresolved_planned_site():
    missing_site = PlannedRef(
        resource_type="site",
        plan_id="sites[99]",
    )

    updated = ResolvedPlanItem(
        plan_id="updates.locations[0]",
        resource_type="location",
        action=PlanAction.UPDATE,
        database_id=71,
        values=ResolvedLocationValues(
            site=missing_site,
            location_type=ExistingRef(
                resource_type="location_type",
                database_id=21,
            ),
            latitude=54.10,
            longitude=13.40,
            height_above_ground=1.30,
            azimuth=180.0,
        ),
        changes=(
            FieldChange(
                field="site",
                before=ExistingRef(
                    resource_type="site",
                    database_id=11,
                ),
                after=missing_site,
                identity_change=True,
            ),
        ),
        source_path="updates.locations[0]",
    )

    plan = ResolvedPlan(
        metadata_items=(updated,),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "location"
    assert errors[0].source_path == "updates.locations[0]"


def test_location_update_rejects_unresolved_planned_location_type():
    missing_type = PlannedRef(
        resource_type="location_type",
        plan_id="location_types[99]",
    )

    updated = ResolvedPlanItem(
        plan_id="updates.locations[0]",
        resource_type="location",
        action=PlanAction.UPDATE,
        database_id=71,
        values=ResolvedLocationValues(
            site=ExistingRef(
                resource_type="site",
                database_id=11,
            ),
            location_type=missing_type,
            latitude=54.10,
            longitude=13.40,
            height_above_ground=1.30,
            azimuth=180.0,
        ),
        changes=(
            FieldChange(
                field="location_type",
                before=ExistingRef(
                    resource_type="location_type",
                    database_id=21,
                ),
                after=missing_type,
                identity_change=False,
            ),
        ),
        source_path="updates.locations[0]",
    )

    plan = ResolvedPlan(
        metadata_items=(updated,),
    )

    errors = collect_plan_consistency_errors(plan)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "location"
    assert errors[0].source_path == "updates.locations[0]"


@pytest.mark.parametrize(
    "successor_action",
    [PlanAction.CREATE, PlanAction.UPDATE],
    ids=["create-successor", "update-successor"],
)
@pytest.mark.parametrize(
    "reverse_order",
    [False, True],
    ids=["closing-first", "successor-first"],
)
@pytest.mark.parametrize(
    "overlaps",
    [False, True],
    ids=["adjacent", "overlapping"],
)
def test_deployment_overlap_uses_final_updated_states(
    successor_action,
    reverse_order,
    overlaps,
):
    january = datetime(2025, 1, 1, tzinfo=timezone.utc)
    february = datetime(2025, 2, 1, tzinfo=timezone.utc)
    march = datetime(2025, 3, 1, tzinfo=timezone.utc)
    june = datetime(2025, 6, 1, tzinfo=timezone.utc)

    closing = _deployment_update_item(
        "updates.deployments[0]",
        41,
        valid_from=january,
        valid_to=march,
    )
    closing = replace(
        closing,
        changes=(
            FieldChange(
                field="valid_to",
                before=june,
                after=march,
            ),
        ),
    )

    existing = (
        ExistingDeploymentState(
            deployment_id=41,
            sensor_id=11,
            variable_id=31,
            valid_from=january,
            valid_to=june,
        ),
    )

    successor_start = february if overlaps else march

    if successor_action == PlanAction.CREATE:
        successor = _deployment_create_item(
            "deployments[0]",
            location_id=22,
            valid_from=successor_start,
            valid_to=None,
        )
    else:
        successor = _deployment_update_item(
            "updates.deployments[1]",
            42,
            location_id=22,
            valid_from=successor_start,
            valid_to=None,
        )
        successor = replace(
            successor,
            changes=(
                FieldChange(
                    field="valid_from",
                    before=june,
                    after=successor_start,
                    identity_change=True,
                ),
            ),
        )
        existing += (
            ExistingDeploymentState(
                deployment_id=42,
                sensor_id=11,
                variable_id=31,
                valid_from=june,
                valid_to=None,
            ),
        )

    items = (closing, successor)
    if reverse_order:
        items = tuple(reversed(items))

    errors = collect_plan_consistency_errors(
        ResolvedPlan(metadata_items=items),
        existing_deployments=existing,
    )

    if overlaps:
        assert len(errors) == 1
        assert errors[0].code == PlanErrorCode.CONFLICT
        assert errors[0].resource_type == "deployment"
        assert errors[0].source_path == items[1].source_path
        assert errors[0].message == (
            "deployment validity interval "
            "overlaps another planned "
            "deployment for the same "
            "sensor and variable"
        )
    else:
        assert errors == ()


def test_deployment_update_keeps_unchanged_history_checks():
    january = datetime(2025, 1, 1, tzinfo=timezone.utc)
    march = datetime(2025, 3, 1, tzinfo=timezone.utc)
    june = datetime(2025, 6, 1, tzinfo=timezone.utc)

    closing = _deployment_update_item(
        "updates.deployments[0]",
        41,
        valid_from=january,
        valid_to=march,
    )
    closing = replace(
        closing,
        changes=(
            FieldChange(
                field="valid_to",
                before=june,
                after=march,
            ),
        ),
    )
    successor = _deployment_create_item(
        "deployments[0]",
        location_id=22,
        valid_from=march,
        valid_to=None,
    )

    existing = (
        ExistingDeploymentState(
            deployment_id=41,
            sensor_id=11,
            variable_id=31,
            valid_from=january,
            valid_to=june,
        ),
        ExistingDeploymentState(
            deployment_id=42,
            sensor_id=11,
            variable_id=31,
            valid_from=june,
            valid_to=None,
        ),
    )

    errors = collect_plan_consistency_errors(
        ResolvedPlan(metadata_items=(closing, successor)),
        existing_deployments=existing,
    )

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "deployment"
    assert errors[0].source_path == successor.source_path
    assert errors[0].message == (
        "deployment validity interval "
        "overlaps an existing deployment "
        "for the same sensor and variable"
    )
