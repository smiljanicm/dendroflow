from dendroflow.configuration.plan import (
    ExistingRef,
    PlanAction,
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


