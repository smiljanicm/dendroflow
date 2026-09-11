from datetime import datetime, timezone

from dendroflow.configuration import metadata
from dendroflow.configuration.metadata import MetadataRow
from dendroflow.configuration.models import ConfigModel
from dendroflow.configuration.plan import (
    ExistingRef,
    PlanAction,
    PlanBinding,
    PlanErrorCode,
)
from dendroflow.configuration.resolution.orchestration import (
    resolve_update_config,
)


def _sensor_row(
    description="Old description",
) -> MetadataRow:
    return MetadataRow(
        database_id=17,
        values={
            "sensor_model_id": 3,
            "serial_number": "OLD123",
            "description": description,
        },
    )


def _deployment_row() -> MetadataRow:
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

def test_resolve_update_config_empty_config():
    plan = resolve_update_config(ConfigModel())

    assert plan.metadata_items == ()
    assert plan.raw_items == ()
    assert plan.bindings == ()
    assert plan.errors == ()
    assert plan.warnings == ()


def test_resolve_update_config_combines_updates(
    monkeypatch,
):
    config = ConfigModel(
        updates={
            "sensors": [
                {
                    "update": {
                        "serial_number": "OLD123",
                    },
                    "set": {
                        "description": "New description",
                    },
                }
            ],
            "deployments": [
                {
                    "update": {
                        "valid_from": (
                            "2025-04-01T00:00:00Z"
                        ),
                    },
                    "set": {
                        "valid_to": (
                            "2025-05-01T00:00:00Z"
                        ),
                    },
                }
            ],
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (_sensor_row(),),
    )
    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (_deployment_row(),),
    )

    plan = resolve_update_config(config)

    assert plan.errors == ()
    assert plan.raw_items == ()
    assert plan.bindings == ()

    assert len(plan.metadata_items) == 2

    assert [
        item.plan_id
        for item in plan.metadata_items
    ] == [
        "updates.sensors[0]",
        "updates.deployments[0]",
    ]

    assert all(
        item.action == PlanAction.UPDATE
        for item in plan.metadata_items
    )


def test_update_error_does_not_block_other_updates(
    monkeypatch,
):
    config = ConfigModel(
        updates={
            "sensors": [
                {
                    "update": {
                        "serial_number": "MISSING",
                    },
                    "set": {
                        "description": "New description",
                    },
                }
            ],
            "deployments": [
                {
                    "update": {
                        "valid_from": (
                            "2025-04-01T00:00:00Z"
                        ),
                    },
                    "set": {
                        "valid_to": (
                            "2025-05-01T00:00:00Z"
                        ),
                    },
                }
            ],
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (),
    )
    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (_deployment_row(),),
    )

    plan = resolve_update_config(config)

    assert len(plan.metadata_items) == 1
    assert (
        plan.metadata_items[0].plan_id
        == "updates.deployments[0]"
    )

    assert len(plan.errors) == 1
    assert plan.errors[0].code == PlanErrorCode.NOT_FOUND
    assert plan.errors[0].source_path == (
        "updates.sensors[0].update"
    )


def test_update_orchestration_omits_noop_updates(
    monkeypatch,
):
    config = ConfigModel(
        updates={
            "sensors": [
                {
                    "update": {
                        "serial_number": "OLD123",
                    },
                    "set": {
                        "description": "Old description",
                    },
                }
            ],
            "deployments": [
                {
                    "update": {
                        "valid_from": (
                            "2025-04-01T00:00:00Z"
                        ),
                    },
                    "set": {
                        "valid_to": (
                            "2025-05-01T00:00:00Z"
                        ),
                    },
                }
            ],
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (_sensor_row(),),
    )
    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (_deployment_row(),),
    )

    plan = resolve_update_config(config)

    assert plan.errors == ()
    assert len(plan.metadata_items) == 1

    assert plan.metadata_items[0].plan_id == (
        "updates.deployments[0]"
    )


def test_update_orchestration_forwards_existing_bindings(
    monkeypatch,
):
    config = ConfigModel(
        references={
            "sensors": {
                "replacement_sensor": {
                    "serial_number": "NEW123",
                }
            }
        },
        updates={
            "deployments": [
                {
                    "update": {
                        "valid_from": (
                            "2025-04-01T00:00:00Z"
                        ),
                    },
                    "set": {
                        "sensor": "replacement_sensor",
                    },
                }
            ]
        },
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (_deployment_row(),),
    )

    replacement = ExistingRef(
        resource_type="sensor",
        database_id=12,
    )

    bindings = (
        PlanBinding(
            resource_type="sensors",
            alias="replacement_sensor",
            resource=replacement,
        ),
    )

    plan = resolve_update_config(
        config,
        existing_bindings=bindings,
    )

    assert plan.errors == ()
    assert len(plan.metadata_items) == 1

    item = plan.metadata_items[0]

    assert item.action == PlanAction.UPDATE
    assert item.values.sensor == replacement

    assert item.changes[0].field == "sensor"
    assert item.changes[0].after == replacement

