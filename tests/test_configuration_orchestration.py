from dendroflow.configuration.models import ConfigModel
from dendroflow.configuration.plan import (
    ExistingRef,
    FieldChange,
    PlanAction,
    PlanBinding,
    PlannedRef,
    ResolvedFileValues,
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSensorValues,
)
from dendroflow.configuration.resolution import orchestration
from dendroflow.configuration.resolution.orchestration import (
    resolve_config,
)


def _sensor_item(
    plan_id: str,
    action: PlanAction,
    database_id: int,
) -> ResolvedPlanItem:
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="sensor",
        action=action,
        database_id=database_id,
        values=ResolvedSensorValues(
            sensor_model=ExistingRef(
                resource_type="sensor_model",
                database_id=3,
            ),
            serial_number="SENSOR123",
            description=None,
        ),
        changes=(
            (
                FieldChange(
                    field="description",
                    before="old",
                    after="new",
                    identity_change=False,
                ),
            )
            if action == PlanAction.UPDATE
            else ()
        ),
        source_path=plan_id,
    )


def _file_item() -> ResolvedPlanItem:
    return ResolvedPlanItem(
        plan_id="files[0]",
        resource_type="file",
        action=PlanAction.CREATE,
        values=ResolvedFileValues(
            filepath="example.dat",
            timestamp_timezone="UTC",
            timestamp_format="%Y-%m-%d %H:%M:%S",
            reader_config={
                "reader": "csv",
                "options": {},
            },
        ),
        source_path="files[0]",
    )


def test_resolve_config_empty_config():
    plan = resolve_config(ConfigModel())

    assert plan.metadata_items == ()
    assert plan.raw_items == ()
    assert plan.bindings == ()
    assert plan.errors == ()
    assert plan.warnings == ()
    assert plan.can_apply is True


def test_resolve_config_combines_subsystem_plans(
    monkeypatch,
):
    config = ConfigModel()

    metadata_item = _sensor_item(
        "sensors[0]",
        PlanAction.REUSE,
        17,
    )
    update_item = _sensor_item(
        "updates.sensors[0]",
        PlanAction.UPDATE,
        18,
    )
    raw_item = _file_item()

    metadata_binding = PlanBinding(
        resource_type="sensors",
        alias="sensor_01",
        resource=ExistingRef(
            resource_type="sensor",
            database_id=17,
        ),
    )
    raw_binding = PlanBinding(
        resource_type="files",
        alias="file_01",
        resource=PlannedRef(
            resource_type="file",
            plan_id="files[0]",
        ),
    )

    metadata_plan = ResolvedPlan(
        metadata_items=(metadata_item,),
        bindings=(metadata_binding,),
    )
    update_plan = ResolvedPlan(
        metadata_items=(update_item,),
    )
    raw_plan = ResolvedPlan(
        raw_items=(raw_item,),
        bindings=(raw_binding,),
    )

    monkeypatch.setattr(
        orchestration,
        "resolve_metadata_config",
        lambda config: metadata_plan,
    )
    monkeypatch.setattr(
        orchestration,
        "resolve_update_config",
        lambda config, existing_bindings=(): update_plan,
    )
    monkeypatch.setattr(
        orchestration,
        "resolve_raw_config",
        lambda config, existing_bindings=(): raw_plan,
    )

    plan = orchestration.resolve_config(config)

    assert plan.metadata_items == (
        metadata_item,
        update_item,
    )
    assert plan.raw_items == (raw_item,)
    assert plan.bindings == (
        metadata_binding,
        raw_binding,
    )
    assert plan.errors == ()
    assert plan.warnings == ()

