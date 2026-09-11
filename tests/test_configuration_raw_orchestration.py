from dendroflow.configuration import raw
from dendroflow.configuration.models import ConfigModel
from dendroflow.configuration.plan import (
    ExistingRef,
    PlanAction,
    PlanBinding,
    PlanErrorCode,
    PlannedRef,
)
from dendroflow.configuration.raw import RawRow
from dendroflow.configuration.resolution.orchestration import (
    resolve_raw_config,
)


def _raw_config() -> ConfigModel:
    return ConfigModel(
        references={
            "deployments": {
                "water_level_main": {
                    "valid_from": "2025-04-01T00:00:00Z",
                }
            }
        },
        files=[
            {
                "ref": "sandhagen_water_table",
                "path": (
                    "tests/data/"
                    "Sandhagen_Rewetted_WaterTbl.dat"
                ),
                "timestamp": {
                    "timezone": "Etc/GMT-1",
                    "format": "%Y-%m-%d %H:%M:%S",
                },
                "reader": {
                    "type": "csv",
                    "options": {
                        "skiprows": [0, 2, 3],
                        "delimiter": ",",
                        "encoding": "utf-8",
                        "na_values": ["NAN"],
                    },
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


def test_resolve_raw_config_empty_config():
    plan = resolve_raw_config(ConfigModel())

    assert plan.metadata_items == ()
    assert plan.raw_items == ()
    assert plan.bindings == ()
    assert plan.errors == ()
    assert plan.warnings == ()


def test_resolve_raw_config_builds_planned_raw_chain(
    monkeypatch,
):
    config = _raw_config()

    monkeypatch.setattr(
        raw,
        "find_file",
        lambda filepath: None,
    )

    deployment_binding = PlanBinding(
        resource_type="deployments",
        alias="water_level_main",
        resource=PlannedRef(
            resource_type="deployment",
            plan_id="deployments[0]",
        ),
    )

    plan = resolve_raw_config(
        config,
        existing_bindings=(deployment_binding,),
    )

    assert plan.metadata_items == ()
    assert plan.errors == ()
    assert plan.warnings == ()

    assert len(plan.raw_items) == 2

    file_item, interface_item = plan.raw_items

    assert file_item.plan_id == "files[0]"
    assert file_item.action == PlanAction.CREATE

    assert interface_item.plan_id == (
        "files[0].interfaces[0]"
    )
    assert interface_item.action == PlanAction.CREATE

    assert interface_item.values.file == PlannedRef(
        resource_type="file",
        plan_id="files[0]",
    )
    assert interface_item.values.deployment == PlannedRef(
        resource_type="deployment",
        plan_id="deployments[0]",
    )

    assert len(plan.bindings) == 1
    assert plan.bindings[0].alias == (
        "sandhagen_water_table"
    )


def test_resolve_raw_config_reuses_existing_raw_chain(
    monkeypatch,
):
    config = _raw_config()

    monkeypatch.setattr(
        raw,
        "find_file",
        lambda filepath: RawRow(
            database_id=3,
            values={
                "filepath": config.files[0].path,
                "timestamp_timezone": "Etc/GMT-1",
                "timestamp_format": (
                    "%Y-%m-%d %H:%M:%S"
                ),
                "reader_config": {
                    "reader": "csv",
                    "options": {
                        "skiprows": [0, 2, 3],
                        "delimiter": ",",
                        "encoding": "utf-8",
                        "na_values": ["NAN"],
                    },
                },
            },
        ),
    )

    monkeypatch.setattr(
        raw,
        "find_file_interfaces",
        lambda file_id: (
            RawRow(
                database_id=7,
                values={
                    "file_id": 3,
                    "deployment_id": 11,
                    "values_column": "Lvl_cm_Avg",
                    "timestamp_column": "TIMESTAMP",
                    "unit": "cm",
                },
            ),
        ),
    )

    deployment_binding = PlanBinding(
        resource_type="deployments",
        alias="water_level_main",
        resource=ExistingRef(
            resource_type="deployment",
            database_id=11,
        ),
    )

    plan = resolve_raw_config(
        config,
        existing_bindings=(deployment_binding,),
    )

    assert plan.errors == ()
    assert len(plan.raw_items) == 2

    file_item, interface_item = plan.raw_items

    assert file_item.action == PlanAction.REUSE
    assert file_item.database_id == 3

    assert interface_item.action == PlanAction.REUSE
    assert interface_item.database_id == 7

    assert plan.bindings[0].resource == ExistingRef(
        resource_type="file",
        database_id=3,
    )


def test_resolve_raw_config_accumulates_file_and_interface_errors(
    monkeypatch,
):
    config = _raw_config()

    monkeypatch.setattr(
        raw,
        "find_file",
        lambda filepath: RawRow(
            database_id=3,
            values={
                "filepath": config.files[0].path,
                "timestamp_timezone": "UTC",
                "timestamp_format": (
                    "%Y-%m-%d %H:%M:%S"
                ),
                "reader_config": {
                    "reader": "csv",
                    "options": {
                        "skiprows": [0, 2, 3],
                        "delimiter": ",",
                        "encoding": "utf-8",
                        "na_values": ["NAN"],
                    },
                },
            },
        ),
    )

    monkeypatch.setattr(
        raw,
        "find_file_interfaces",
        lambda file_id: (),
    )

    plan = resolve_raw_config(
        config,
        existing_bindings=(),
    )

    assert len(plan.raw_items) == 1

    file_item = plan.raw_items[0]

    assert file_item.action == PlanAction.REUSE
    assert file_item.database_id == 3

    assert len(plan.errors) == 2

    assert {
        error.code
        for error in plan.errors
    } == {
        PlanErrorCode.CONFLICT,
        PlanErrorCode.INVALID_REFERENCE,
    }

    assert {
        error.source_path
        for error in plan.errors
    } == {
        "files[0].timestamp_timezone",
        "files[0].interfaces[0].deployment",
    }

