from datetime import datetime, timezone

from dendroflow.configuration import metadata, raw
from dendroflow.configuration.metadata import MetadataRow
from dendroflow.configuration.models import ConfigModel
from dendroflow.configuration.plan import (
    ExistingRef,
    FieldChange,
    PlanAction,
    PlanBinding,
    PlanError,
    PlanErrorCode,
    PlannedRef,
    PlanWarning,
    ResolvedFileValues,
    ResolvedInterfaceValues,
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


def test_resolve_config_forwards_metadata_bindings(
    monkeypatch,
):
    config = ConfigModel()

    metadata_binding = PlanBinding(
        resource_type="sensors",
        alias="sensor_01",
        resource=ExistingRef(
            resource_type="sensor",
            database_id=17,
        ),
    )

    metadata_plan = ResolvedPlan(
        bindings=(metadata_binding,),
    )

    received_update_bindings = []
    received_raw_bindings = []

    def fake_resolve_update_config(
        config,
        existing_bindings=(),
    ):
        received_update_bindings.append(existing_bindings)
        return ResolvedPlan()

    def fake_resolve_raw_config(
        config,
        existing_bindings=(),
    ):
        received_raw_bindings.append(existing_bindings)
        return ResolvedPlan()

    monkeypatch.setattr(
        orchestration,
        "resolve_metadata_config",
        lambda config: metadata_plan,
    )
    monkeypatch.setattr(
        orchestration,
        "resolve_update_config",
        fake_resolve_update_config,
    )
    monkeypatch.setattr(
        orchestration,
        "resolve_raw_config",
        fake_resolve_raw_config,
    )

    plan = resolve_config(config)

    assert received_update_bindings == [
        (metadata_binding,)
    ]
    assert received_raw_bindings == [
        (metadata_binding,)
    ]

    assert plan.bindings == (
        metadata_binding,
    )


def test_resolve_config_preserves_plan_order(
    monkeypatch,
):
    config = ConfigModel()

    metadata_item_1 = _sensor_item(
        "sensors[0]",
        PlanAction.REUSE,
        17,
    )
    metadata_item_2 = _sensor_item(
        "sensors[1]",
        PlanAction.REUSE,
        18,
    )

    update_item_1 = _sensor_item(
        "updates.sensors[0]",
        PlanAction.UPDATE,
        19,
    )
    update_item_2 = _sensor_item(
        "updates.sensors[1]",
        PlanAction.UPDATE,
        20,
    )

    raw_item_1 = _file_item()

    raw_item_2 = ResolvedPlanItem(
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
            timestamp_column="TIMESTAMP",
            values_column="Lvl_cm_Avg",
            unit="cm",
        ),
        source_path="files[0].interfaces[0]",
    )

    metadata_plan = ResolvedPlan(
        metadata_items=(
            metadata_item_1,
            metadata_item_2,
        ),
    )

    update_plan = ResolvedPlan(
        metadata_items=(
            update_item_1,
            update_item_2,
        ),
    )

    raw_plan = ResolvedPlan(
        raw_items=(
            raw_item_1,
            raw_item_2,
        ),
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

    plan = resolve_config(config)

    assert [
        item.plan_id
        for item in plan.metadata_items
    ] == [
        "sensors[0]",
        "sensors[1]",
        "updates.sensors[0]",
        "updates.sensors[1]",
    ]

    assert [
        item.plan_id
        for item in plan.raw_items
    ] == [
        "files[0]",
        "files[0].interfaces[0]",
    ]


# Error propagation


def test_resolve_config_aggregates_errors_in_subsystem_order(
    monkeypatch,
):
    config = ConfigModel()

    metadata_error = PlanError(
        code=PlanErrorCode.NOT_FOUND,
        resource_type="sensor",
        source_path="sensors[0]",
        message="metadata error",
    )
    update_error = PlanError(
        code=PlanErrorCode.AMBIGUOUS,
        resource_type="sensor",
        source_path="updates.sensors[0].update",
        message="update error",
    )
    raw_error = PlanError(
        code=PlanErrorCode.INVALID_REFERENCE,
        resource_type="interface",
        source_path="files[0].interfaces[0].deployment",
        message="raw error",
    )

    monkeypatch.setattr(
        orchestration,
        "resolve_metadata_config",
        lambda config: ResolvedPlan(
            errors=(metadata_error,),
        ),
    )
    monkeypatch.setattr(
        orchestration,
        "resolve_update_config",
        lambda config, existing_bindings=(): ResolvedPlan(
            errors=(update_error,),
        ),
    )
    monkeypatch.setattr(
        orchestration,
        "resolve_raw_config",
        lambda config, existing_bindings=(): ResolvedPlan(
            errors=(raw_error,),
        ),
    )

    plan = resolve_config(config)

    assert plan.errors == (
        metadata_error,
        update_error,
        raw_error,
    )


def test_resolve_config_aggregates_warnings_in_subsystem_order(
    monkeypatch,
):
    config = ConfigModel()

    metadata_warning = PlanWarning(
        code="metadata_warning",
        source_path="sensors[0]",
        message="metadata warning",
    )
    update_warning = PlanWarning(
        code="update_warning",
        source_path="updates.sensors[0]",
        message="update warning",
    )
    raw_warning = PlanWarning(
        code="raw_warning",
        source_path="files[0]",
        message="raw warning",
    )

    monkeypatch.setattr(
        orchestration,
        "resolve_metadata_config",
        lambda config: ResolvedPlan(
            warnings=(metadata_warning,),
        ),
    )
    monkeypatch.setattr(
        orchestration,
        "resolve_update_config",
        lambda config, existing_bindings=(): ResolvedPlan(
            warnings=(update_warning,),
        ),
    )
    monkeypatch.setattr(
        orchestration,
        "resolve_raw_config",
        lambda config, existing_bindings=(): ResolvedPlan(
            warnings=(raw_warning,),
        ),
    )

    plan = resolve_config(config)

    assert plan.warnings == (
        metadata_warning,
        update_warning,
        raw_warning,
    )


def test_resolve_config_keeps_items_when_other_subsystem_has_error(
    monkeypatch,
):
    config = ConfigModel()

    metadata_item = _sensor_item(
        "sensors[0]",
        PlanAction.REUSE,
        17,
    )
    raw_item = _file_item()

    update_error = PlanError(
        code=PlanErrorCode.NOT_FOUND,
        resource_type="sensor",
        source_path="updates.sensors[0].update",
        message="sensor not found",
    )

    monkeypatch.setattr(
        orchestration,
        "resolve_metadata_config",
        lambda config: ResolvedPlan(
            metadata_items=(metadata_item,),
        ),
    )
    monkeypatch.setattr(
        orchestration,
        "resolve_update_config",
        lambda config, existing_bindings=(): ResolvedPlan(
            errors=(update_error,),
        ),
    )
    monkeypatch.setattr(
        orchestration,
        "resolve_raw_config",
        lambda config, existing_bindings=(): ResolvedPlan(
            raw_items=(raw_item,),
        ),
    )

    plan = resolve_config(config)

    assert plan.metadata_items == (metadata_item,)
    assert plan.raw_items == (raw_item,)
    assert plan.errors == (update_error,)


def test_resolve_config_with_error_cannot_apply(
    monkeypatch,
):
    config = ConfigModel()

    error = PlanError(
        code=PlanErrorCode.CONFLICT,
        resource_type="file",
        source_path="files[0].reader_config",
        message="file configuration conflict",
    )

    monkeypatch.setattr(
        orchestration,
        "resolve_metadata_config",
        lambda config: ResolvedPlan(),
    )
    monkeypatch.setattr(
        orchestration,
        "resolve_update_config",
        lambda config, existing_bindings=(): ResolvedPlan(),
    )
    monkeypatch.setattr(
        orchestration,
        "resolve_raw_config",
        lambda config, existing_bindings=(): ResolvedPlan(
            errors=(error,),
        ),
    )

    plan = resolve_config(config)

    assert plan.errors == (error,)
    assert plan.can_apply is False


# Hardening tests


def _existing_deployment_row() -> MetadataRow:
    return MetadataRow(
        database_id=41,
        values={
            "sensor_id": 11,
            "location_id": 21,
            "variable_id": 31,
            "valid_from": datetime(
                2025,
                4,
                1,
                tzinfo=timezone.utc,
            ),
            "valid_to": None,
        },
    )


def test_resolve_config_builds_mixed_full_plan(
    monkeypatch,
):
    config = ConfigModel(
        sites=[
            {
                "ref": "new_site",
                "site_code": "NEW",
                "name": "New site",
            }
        ],
        references={
            "deployments": {
                "water_level_main": {
                    "valid_from": (
                        "2025-04-01T00:00:00Z"
                    ),
                }
            }
        },
        updates={
            "sensors": [
                {
                    "update": {
                        "serial_number": "OLD123",
                    },
                    "set": {
                        "serial_number": "NEW123",
                    },
                }
            ]
        },
        files=[
            {
                "ref": "water_table_file",
                "path": "tests/data/example.dat",
                "timestamp": {
                    "timezone": "UTC",
                    "format": "%Y-%m-%d %H:%M:%S",
                },
                "reader": {
                    "type": "csv",
                    "options": {},
                },
                "interfaces": [
                    {
                        "deployment": "water_level_main",
                        "timestamp_column": "TIMESTAMP",
                        "values_column": "Lvl_cm_Avg",
                        "unit": "cm",
                    }
                ],
            }
        ],
    )

    monkeypatch.setattr(
        metadata,
        "find_site",
        lambda site_code: None,
    )
    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (_existing_deployment_row(),),
    )
    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (
            MetadataRow(
                database_id=17,
                values={
                    "sensor_model_id": 3,
                    "serial_number": "OLD123",
                    "description": None,
                },
            ),
        ),
    )
    monkeypatch.setattr(
        raw,
        "find_file",
        lambda filepath: None,
    )

    plan = resolve_config(config)

    assert plan.errors == ()

    assert [
        item.plan_id
        for item in plan.metadata_items
    ] == [
        "sites[0]",
        "updates.sensors[0]",
    ]

    assert [
        item.plan_id
        for item in plan.raw_items
    ] == [
        "files[0]",
        "files[0].interfaces[0]",
    ]

    assert (
        plan.raw_items[1].values.deployment
        == ExistingRef(
            resource_type="deployment",
            database_id=41,
        )
    )

    assert plan.requires_confirmation is True
    assert plan.can_apply is True


def test_metadata_error_does_not_block_independent_raw_branch(
    monkeypatch,
):
    config = ConfigModel(
        references={
            "sites": {
                "missing_site": {
                    "site_code": "MISSING",
                }
            },
            "deployments": {
                "water_level_main": {
                    "valid_from": (
                        "2025-04-01T00:00:00Z"
                    ),
                }
            },
        },
        files=[
            {
                "path": "tests/data/example.dat",
                "timestamp": {
                    "timezone": "UTC",
                    "format": "%Y-%m-%d %H:%M:%S",
                },
                "reader": {
                    "type": "csv",
                    "options": {},
                },
                "interfaces": [
                    {
                        "deployment": "water_level_main",
                        "timestamp_column": "TIMESTAMP",
                        "values_column": "Lvl_cm_Avg",
                        "unit": "cm",
                    }
                ],
            }
        ],
    )

    monkeypatch.setattr(
        metadata,
        "find_site",
        lambda site_code: None,
    )
    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (_existing_deployment_row(),),
    )
    monkeypatch.setattr(
        raw,
        "find_file",
        lambda filepath: None,
    )

    plan = resolve_config(config)

    assert len(plan.errors) == 1
    assert plan.errors[0].code == PlanErrorCode.NOT_FOUND

    assert [
        item.plan_id
        for item in plan.raw_items
    ] == [
        "files[0]",
        "files[0].interfaces[0]",
    ]

    assert plan.can_apply is False


def test_planned_deployment_flows_into_raw_interface(
    monkeypatch,
):
    config = ConfigModel(
        references={
            "sensors": {
                "sensor_main": {
                    "serial_number": "SENSOR123",
                }
            },
            "locations": {
                "location_main": {
                    "initial_label": "Well 1",
                }
            },
            "variables": {
                "water_level": {
                    "variable": "water_level",
                }
            },
        },
        deployments=[
            {
                "ref": "water_level_main",
                "sensor": "sensor_main",
                "location": "location_main",
                "variable": "water_level",
                "valid_from": (
                    "2025-04-01T00:00:00Z"
                ),
            }
        ],
        files=[
            {
                "path": "tests/data/example.dat",
                "timestamp": {
                    "timezone": "UTC",
                    "format": "%Y-%m-%d %H:%M:%S",
                },
                "reader": {
                    "type": "csv",
                    "options": {},
                },
                "interfaces": [
                    {
                        "deployment": "water_level_main",
                        "timestamp_column": "TIMESTAMP",
                        "values_column": "Lvl_cm_Avg",
                        "unit": "cm",
                    }
                ],
            }
        ],
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (
            MetadataRow(
                database_id=11,
                values={
                    "sensor_model_id": 3,
                    "serial_number": "SENSOR123",
                    "description": None,
                },
            ),
        ),
    )
    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (
            MetadataRow(
                database_id=21,
                values={
                    "site_id": 1,
                    "location_type_id": 2,
                    "latitude": None,
                    "longitude": None,
                    "height_above_ground": None,
                    "azimuth": None,
                    "initial_label": "Well 1",
                    "initial_label_valid_from": datetime(
                        2024,
                        1,
                        1,
                        tzinfo=timezone.utc,
                    ),
                    "initial_label_valid_to": None,
                },
            ),
        ),
    )
    monkeypatch.setattr(
        metadata,
        "find_variable",
        lambda variable: MetadataRow(
            database_id=31,
            values={
                "variable": "water_level",
                "derived": False,
                "description": None,
            },
        ),
    )
    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (),
    )
    monkeypatch.setattr(
        raw,
        "find_file",
        lambda filepath: None,
    )

    plan = resolve_config(config)

    assert plan.errors == ()

    deployment_item = next(
        item
        for item in plan.metadata_items
        if item.plan_id == "deployments[0]"
    )

    assert deployment_item.action == PlanAction.CREATE

    interface_item = next(
        item
        for item in plan.raw_items
        if item.plan_id == "files[0].interfaces[0]"
    )

    assert interface_item.values.deployment == PlannedRef(
        resource_type="deployment",
        plan_id="deployments[0]",
    )

    assert plan.can_apply is True

