from datetime import datetime, timezone

from dendroflow.configuration import metadata
from dendroflow.configuration.metadata import MetadataRow
from dendroflow.configuration.models import ConfigModel
from dendroflow.configuration.plan import (
    ExistingRef,
    PlanAction,
    PlanBinding,
    PlanErrorCode,
    PlannedRef,
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


# Hardening tests


def test_multiple_sensor_updates_mix_update_and_noop(
    monkeypatch,
):
    config = ConfigModel(
        updates={
            "sensors": [
                {
                    "update": {
                        "serial_number": "SENSOR_A",
                    },
                    "set": {
                        "description": "New description",
                    },
                },
                {
                    "update": {
                        "serial_number": "SENSOR_B",
                    },
                    "set": {
                        "description": "Already correct",
                    },
                },
            ]
        }
    )

    def fake_find_sensors(**kwargs):
        serial_number = kwargs["serial_number"]

        if serial_number == "SENSOR_A":
            return (
                MetadataRow(
                    database_id=17,
                    values={
                        "sensor_model_id": 3,
                        "serial_number": "SENSOR_A",
                        "description": "Old description",
                    },
                ),
            )

        if serial_number == "SENSOR_B":
            return (
                MetadataRow(
                    database_id=18,
                    values={
                        "sensor_model_id": 3,
                        "serial_number": "SENSOR_B",
                        "description": "Already correct",
                    },
                ),
            )

        return ()

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        fake_find_sensors,
    )

    plan = resolve_update_config(config)

    assert plan.errors == ()
    assert len(plan.metadata_items) == 1

    assert plan.metadata_items[0].plan_id == (
        "updates.sensors[0]"
    )
    assert plan.metadata_items[0].database_id == 17


def test_invalid_deployment_update_does_not_block_valid_sibling(
    monkeypatch,
):
    config = ConfigModel(
        updates={
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
                },
                {
                    "update": {
                        "valid_from": (
                            "2025-04-02T00:00:00Z"
                        ),
                    },
                    "set": {
                        "valid_to": (
                            "2025-06-01T00:00:00Z"
                        ),
                    },
                },
            ]
        }
    )

    def fake_find_deployments(**kwargs):
        if kwargs["valid_from"] == datetime(
            2025,
            4,
            1,
            tzinfo=timezone.utc,
        ):
            return (_deployment_row(),)

        return ()

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        fake_find_deployments,
    )

    plan = resolve_update_config(config)

    assert len(plan.metadata_items) == 1
    assert plan.metadata_items[0].plan_id == (
        "updates.deployments[0]"
    )

    assert len(plan.errors) == 1
    assert plan.errors[0].code == PlanErrorCode.NOT_FOUND
    assert plan.errors[0].source_path == (
        "updates.deployments[1].update"
    )


def test_ambiguous_sensor_update_does_not_block_valid_update(
    monkeypatch,
):
    config = ConfigModel(
        updates={
            "sensors": [
                {
                    "update": {
                        "serial_number": "AMBIGUOUS",
                    },
                    "set": {
                        "description": "Changed",
                    },
                },
                {
                    "update": {
                        "serial_number": "VALID",
                    },
                    "set": {
                        "description": "Changed",
                    },
                },
            ]
        }
    )

    def fake_find_sensors(**kwargs):
        if kwargs["serial_number"] == "AMBIGUOUS":
            return (
                MetadataRow(17, {}),
                MetadataRow(18, {}),
            )

        return (
            MetadataRow(
                database_id=19,
                values={
                    "sensor_model_id": 3,
                    "serial_number": "VALID",
                    "description": "Old",
                },
            ),
        )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        fake_find_sensors,
    )

    plan = resolve_update_config(config)

    assert len(plan.metadata_items) == 1
    assert plan.metadata_items[0].database_id == 19

    assert len(plan.errors) == 1
    assert plan.errors[0].code == PlanErrorCode.AMBIGUOUS


def test_deployment_update_accumulates_set_reference_errors(
    monkeypatch,
):
    config = ConfigModel(
        references={
            "sensors": {
                "missing_sensor": {
                    "serial_number": "X",
                }
            },
            "locations": {
                "missing_location": {
                    "site": "some_site",
                    "initial_label": "some_label",
                }
            },
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
                        "sensor": "missing_sensor",
                        "location": "missing_location",
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

    plan = resolve_update_config(
        config,
        existing_bindings=(),
    )

    assert plan.metadata_items == ()
    assert len(plan.errors) == 2

    assert {
        error.source_path
        for error in plan.errors
    } == {
        "updates.deployments[0].set.sensor",
        "updates.deployments[0].set.location",
    }

    assert all(
        error.code == PlanErrorCode.INVALID_REFERENCE
        for error in plan.errors
    )


def test_planned_relationship_target_survives_update_orchestration(
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

    planned_sensor = PlannedRef(
        resource_type="sensor",
        plan_id="sensors[0]",
    )

    bindings = (
        PlanBinding(
            resource_type="sensors",
            alias="replacement_sensor",
            resource=planned_sensor,
        ),
    )

    plan = resolve_update_config(
        config,
        existing_bindings=bindings,
    )

    assert plan.errors == ()
    assert len(plan.metadata_items) == 1

    item = plan.metadata_items[0]

    assert item.values.sensor == planned_sensor
    assert item.changes[0].after == planned_sensor


def test_update_plan_has_deterministic_order(
    monkeypatch,
):
    config = ConfigModel(
        updates={
            "sensors": [
                {
                    "update": {
                        "serial_number": "A",
                    },
                    "set": {
                        "description": "New A",
                    },
                },
                {
                    "update": {
                        "serial_number": "B",
                    },
                    "set": {
                        "description": "New B",
                    },
                },
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

    def fake_find_sensors(**kwargs):
        serial = kwargs["serial_number"]

        return (
            MetadataRow(
                database_id=17 if serial == "A" else 18,
                values={
                    "sensor_model_id": 3,
                    "serial_number": serial,
                    "description": f"Old {serial}",
                },
            ),
        )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        fake_find_sensors,
    )
    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (_deployment_row(),),
    )

    plan = resolve_update_config(config)

    assert plan.errors == ()

    assert [
        item.plan_id
        for item in plan.metadata_items
    ] == [
        "updates.sensors[0]",
        "updates.sensors[1]",
        "updates.deployments[0]",
    ]


def test_update_plan_preserves_confirmation_requirements(
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
                },
                {
                    "update": {
                        "serial_number": "IDENTITY",
                    },
                    "set": {
                        "serial_number": "IDENTITY_NEW",
                    },
                },
            ]
        }
    )

    def fake_find_sensors(**kwargs):
        serial = kwargs["serial_number"]

        if serial == "OLD123":
            return (_sensor_row(),)

        return (
            MetadataRow(
                database_id=18,
                values={
                    "sensor_model_id": 3,
                    "serial_number": "IDENTITY",
                    "description": None,
                },
            ),
        )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        fake_find_sensors,
    )

    plan = resolve_update_config(config)

    assert plan.errors == ()

    assert [
        item.requires_confirmation
        for item in plan.metadata_items
    ] == [
        False,
        True,
    ]

    assert plan.requires_confirmation is True


def test_noop_only_update_config_produces_empty_plan(
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
                        "valid_to": None,
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

    assert plan.metadata_items == ()
    assert plan.raw_items == ()
    assert plan.errors == ()
    assert plan.bindings == ()
    assert plan.requires_confirmation is False

