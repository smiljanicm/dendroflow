from dendroflow.configuration import metadata
from dendroflow.configuration.metadata import MetadataRow
from dendroflow.configuration.models import ConfigModel
from dendroflow.configuration.plan import (
    ExistingRef,
    PlanAction,
    PlanErrorCode,
)
from dendroflow.configuration.resolution.updates import (
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


