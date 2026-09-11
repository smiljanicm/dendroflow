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
from dendroflow.configuration.resolution.updates import (
    resolve_deployment_updates,
    resolve_sensor_updates,
)


def _sensor_update_config(
    set_values: dict[str, object],
) -> ConfigModel:
    return ConfigModel(
        updates={
            "sensors": [
                {
                    "update": {
                        "serial_number": "OLD123",
                    },
                    "set": set_values,
                }
            ]
        }
    )


def _sensor_row(
    *,
    serial_number="OLD123",
    description="Old description",
) -> MetadataRow:
    return MetadataRow(
        database_id=17,
        values={
            "sensor_model_id": 3,
            "serial_number": serial_number,
            "description": description,
        },
    )


def test_sensor_description_change_becomes_update(
    monkeypatch,
):
    config = _sensor_update_config(
        {
            "description": "New description",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (_sensor_row(),),
    )

    items, errors = resolve_sensor_updates(config)

    assert errors == ()
    assert len(items) == 1

    item = items[0]

    assert item.plan_id == "updates.sensors[0]"
    assert item.resource_type == "sensor"
    assert item.action == PlanAction.UPDATE
    assert item.database_id == 17

    assert len(item.changes) == 1

    change = item.changes[0]

    assert change.field == "description"
    assert change.before == "Old description"
    assert change.after == "New description"
    assert change.identity_change is False

    assert item.values.serial_number == "OLD123"
    assert item.values.sensor_model == ExistingRef(
        resource_type="sensor_model",
        database_id=3,
    )
    assert item.values.description == "New description"


def test_sensor_serial_number_change_is_identity_change(
    monkeypatch,
):
    config = _sensor_update_config(
        {
            "serial_number": "NEW123",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (_sensor_row(),),
    )

    items, errors = resolve_sensor_updates(config)

    assert errors == ()
    assert len(items) == 1

    item = items[0]

    assert item.action == PlanAction.UPDATE
    assert item.database_id == 17

    assert len(item.changes) == 1

    change = item.changes[0]

    assert change.field == "serial_number"
    assert change.before == "OLD123"
    assert change.after == "NEW123"
    assert change.identity_change is True

    assert item.values.serial_number == "NEW123"
    assert item.values.description == "Old description"


def test_sensor_update_retains_multiple_changes(
    monkeypatch,
):
    config = _sensor_update_config(
        {
            "serial_number": "NEW123",
            "description": "New description",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (_sensor_row(),),
    )

    items, errors = resolve_sensor_updates(config)

    assert errors == ()
    assert len(items) == 1

    item = items[0]

    assert item.action == PlanAction.UPDATE

    assert [
        change.field
        for change in item.changes
    ] == [
        "serial_number",
        "description",
    ]

    assert item.changes[0].identity_change is True
    assert item.changes[1].identity_change is False

    assert item.values.serial_number == "NEW123"
    assert item.values.description == "New description"


def test_sensor_update_with_no_actual_change_is_noop(
    monkeypatch,
):
    config = _sensor_update_config(
        {
            "description": "Old description",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (_sensor_row(),),
    )

    items, errors = resolve_sensor_updates(config)

    assert items == ()
    assert errors == ()


def test_sensor_update_can_clear_description(
    monkeypatch,
):
    config = _sensor_update_config(
        {
            "description": None,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (_sensor_row(),),
    )

    items, errors = resolve_sensor_updates(config)

    assert errors == ()
    assert len(items) == 1

    item = items[0]

    assert len(item.changes) == 1

    change = item.changes[0]

    assert change.field == "description"
    assert change.before == "Old description"
    assert change.after is None
    assert change.identity_change is False

    assert item.values.description is None


def test_sensor_update_propagates_not_found(
    monkeypatch,
):
    config = _sensor_update_config(
        {
            "description": "New description",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (),
    )

    items, errors = resolve_sensor_updates(config)

    assert items == ()
    assert len(errors) == 1

    assert errors[0].code == PlanErrorCode.NOT_FOUND
    assert errors[0].resource_type == "sensor"
    assert errors[0].source_path == (
        "updates.sensors[0].update"
    )


def test_sensor_update_propagates_ambiguous_selector(
    monkeypatch,
):
    config = _sensor_update_config(
        {
            "description": "New description",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (
            MetadataRow(
                database_id=17,
                values={},
            ),
            MetadataRow(
                database_id=18,
                values={},
            ),
        ),
    )

    items, errors = resolve_sensor_updates(config)

    assert items == ()
    assert len(errors) == 1

    assert errors[0].code == PlanErrorCode.AMBIGUOUS
    assert errors[0].candidate_ids == (17, 18)
    assert errors[0].source_path == (
        "updates.sensors[0].update"
    )


# Deployment


def _deployment_update_config(
    set_values: dict[str, object],
) -> ConfigModel:
    return ConfigModel(
        updates={
            "deployments": [
                {
                    "update": {
                        "valid_from": (
                            "2025-04-01T00:00:00Z"
                        ),
                    },
                    "set": set_values,
                }
            ]
        }
    )


def _deployment_row(
    *,
    sensor_id=11,
    location_id=21,
    variable_id=31,
    valid_from=None,
    valid_to=None,
) -> MetadataRow:
    if valid_from is None:
        valid_from = datetime(
            2025,
            4,
            1,
            tzinfo=timezone.utc,
        )

    return MetadataRow(
        database_id=41,
        values={
            "sensor_id": sensor_id,
            "location_id": location_id,
            "variable_id": variable_id,
            "valid_from": valid_from,
            "valid_to": valid_to,
        },
    )


def test_deployment_valid_to_change_becomes_update(
    monkeypatch,
):
    new_valid_to = datetime(
        2025,
        5,
        1,
        tzinfo=timezone.utc,
    )

    config = _deployment_update_config(
        {
            "valid_to": new_valid_to,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (_deployment_row(),),
    )

    items, errors = resolve_deployment_updates(config)

    assert errors == ()
    assert len(items) == 1

    item = items[0]

    assert item.plan_id == "updates.deployments[0]"
    assert item.resource_type == "deployment"
    assert item.action == PlanAction.UPDATE
    assert item.database_id == 41

    assert len(item.changes) == 1

    change = item.changes[0]

    assert change.field == "valid_to"
    assert change.before is None
    assert change.after == new_valid_to
    assert change.identity_change is False

    assert item.values.valid_to == new_valid_to


def test_deployment_valid_from_change_is_identity_change(
    monkeypatch,
):
    new_valid_from = datetime(
        2025,
        4,
        2,
        tzinfo=timezone.utc,
    )

    config = _deployment_update_config(
        {
            "valid_from": new_valid_from,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (_deployment_row(),),
    )

    items, errors = resolve_deployment_updates(config)

    assert errors == ()
    assert len(items) == 1

    change = items[0].changes[0]

    assert change.field == "valid_from"
    assert change.before == datetime(
        2025,
        4,
        1,
        tzinfo=timezone.utc,
    )
    assert change.after == new_valid_from
    assert change.identity_change is True


def test_deployment_update_with_no_actual_change_is_noop(
    monkeypatch,
):
    config = _deployment_update_config(
        {
            "valid_to": None,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (_deployment_row(),),
    )

    items, errors = resolve_deployment_updates(config)

    assert items == ()
    assert errors == ()


def test_deployment_update_propagates_not_found(
    monkeypatch,
):
    config = _deployment_update_config(
        {
            "valid_to": datetime(
                2025,
                5,
                1,
                tzinfo=timezone.utc,
            ),
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (),
    )

    items, errors = resolve_deployment_updates(config)

    assert items == ()
    assert len(errors) == 1

    assert errors[0].code == PlanErrorCode.NOT_FOUND
    assert errors[0].resource_type == "deployment"
    assert errors[0].source_path == (
        "updates.deployments[0].update"
    )


def test_deployment_sensor_change_to_existing_resource(
    monkeypatch,
):
    config = _deployment_update_config(
        {
            "sensor": "replacement_sensor",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (_deployment_row(),),
    )

    bindings = (
        PlanBinding(
            resource_type="sensors",
            alias="replacement_sensor",
            resource=ExistingRef(
                resource_type="sensor",
                database_id=12,
            ),
        ),
    )

    items, errors = resolve_deployment_updates(
        config,
        existing_bindings=bindings,
    )

    assert errors == ()
    assert len(items) == 1

    item = items[0]

    change = item.changes[0]

    assert change.field == "sensor"
    assert change.before == ExistingRef(
        resource_type="sensor",
        database_id=11,
    )
    assert change.after == ExistingRef(
        resource_type="sensor",
        database_id=12,
    )
    assert change.identity_change is True

    assert item.values.sensor == ExistingRef(
        resource_type="sensor",
        database_id=12,
    )


def test_deployment_sensor_change_to_planned_resource(
    monkeypatch,
):
    config = _deployment_update_config(
        {
            "sensor": "replacement_sensor",
        }
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

    items, errors = resolve_deployment_updates(
        config,
        existing_bindings=bindings,
    )

    assert errors == ()
    assert len(items) == 1

    change = items[0].changes[0]

    assert change.field == "sensor"
    assert change.before == ExistingRef(
        resource_type="sensor",
        database_id=11,
    )
    assert change.after == planned_sensor
    assert change.identity_change is True

    assert items[0].values.sensor == planned_sensor


def test_deployment_update_missing_set_binding_is_invalid(
    monkeypatch,
):
    config = _deployment_update_config(
        {
            "sensor": "missing_sensor",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (_deployment_row(),),
    )

    items, errors = resolve_deployment_updates(
        config,
        existing_bindings=(),
    )

    assert items == ()
    assert len(errors) == 1

    assert (
        errors[0].code
        == PlanErrorCode.INVALID_REFERENCE
    )
    assert errors[0].resource_type == "deployment"
    assert errors[0].source_path == (
        "updates.deployments[0].set.sensor"
    )


def test_deployment_update_retains_multiple_changes(
    monkeypatch,
):
    new_valid_from = datetime(
        2025,
        4,
        2,
        tzinfo=timezone.utc,
    )
    new_valid_to = datetime(
        2025,
        5,
        1,
        tzinfo=timezone.utc,
    )

    config = _deployment_update_config(
        {
            "sensor": "replacement_sensor",
            "location": "replacement_location",
            "variable": "replacement_variable",
            "valid_from": new_valid_from,
            "valid_to": new_valid_to,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (_deployment_row(),),
    )

    bindings = (
        PlanBinding(
            resource_type="sensors",
            alias="replacement_sensor",
            resource=ExistingRef(
                resource_type="sensor",
                database_id=12,
            ),
        ),
        PlanBinding(
            resource_type="locations",
            alias="replacement_location",
            resource=ExistingRef(
                resource_type="location",
                database_id=22,
            ),
        ),
        PlanBinding(
            resource_type="variables",
            alias="replacement_variable",
            resource=ExistingRef(
                resource_type="variable",
                database_id=32,
            ),
        ),
    )

    items, errors = resolve_deployment_updates(
        config,
        existing_bindings=bindings,
    )

    assert errors == ()
    assert len(items) == 1

    item = items[0]

    assert [
        change.field
        for change in item.changes
    ] == [
        "sensor",
        "location",
        "variable",
        "valid_from",
        "valid_to",
    ]

    assert [
        change.identity_change
        for change in item.changes
    ] == [
        True,
        True,
        True,
        True,
        False,
    ]


# Additional tests


def test_sensor_description_update_does_not_require_confirmation(
    monkeypatch,
):
    config = _sensor_update_config(
        {
            "description": "New description",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (_sensor_row(),),
    )

    items, errors = resolve_sensor_updates(config)

    assert errors == ()
    assert len(items) == 1
    assert items[0].requires_confirmation is False


def test_sensor_serial_number_update_requires_confirmation(
    monkeypatch,
):
    config = _sensor_update_config(
        {
            "serial_number": "NEW123",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (_sensor_row(),),
    )

    items, errors = resolve_sensor_updates(config)

    assert errors == ()
    assert len(items) == 1
    assert items[0].requires_confirmation is True


def test_deployment_valid_to_update_does_not_require_confirmation(
    monkeypatch,
):
    new_valid_to = datetime(
        2025,
        5,
        1,
        tzinfo=timezone.utc,
    )

    config = _deployment_update_config(
        {
            "valid_to": new_valid_to,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (_deployment_row(),),
    )

    items, errors = resolve_deployment_updates(config)

    assert errors == ()
    assert len(items) == 1
    assert items[0].requires_confirmation is False


def test_deployment_identity_update_requires_confirmation(
    monkeypatch,
):
    new_valid_from = datetime(
        2025,
        4,
        2,
        tzinfo=timezone.utc,
    )

    config = _deployment_update_config(
        {
            "valid_from": new_valid_from,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (_deployment_row(),),
    )

    items, errors = resolve_deployment_updates(config)

    assert errors == ()
    assert len(items) == 1
    assert items[0].requires_confirmation is True


def test_mixed_deployment_update_requires_confirmation(
    monkeypatch,
):
    new_valid_from = datetime(
        2025,
        4,
        2,
        tzinfo=timezone.utc,
    )
    new_valid_to = datetime(
        2025,
        5,
        1,
        tzinfo=timezone.utc,
    )

    config = _deployment_update_config(
        {
            "valid_from": new_valid_from,
            "valid_to": new_valid_to,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (_deployment_row(),),
    )

    items, errors = resolve_deployment_updates(config)

    assert errors == ()
    assert len(items) == 1

    item = items[0]

    assert [
        change.identity_change
        for change in item.changes
    ] == [
        True,
        False,
    ]
    assert item.requires_confirmation is True

