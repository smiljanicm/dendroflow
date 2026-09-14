from datetime import datetime, timezone

from dendroflow.configuration import metadata
from dendroflow.configuration.metadata import MetadataRow
from dendroflow.configuration.models import ConfigModel
from dendroflow.configuration.plan import (
    ExistingRef,
    FieldChange,
    PlanAction,
    PlanBinding,
    PlanErrorCode,
    PlannedRef,
)
from dendroflow.configuration.resolution.updates import (
    resolve_deployment_updates,
    resolve_location_type_updates,
    resolve_location_updates,
    resolve_sensor_model_updates,
    resolve_sensor_type_updates,
    resolve_sensor_updates,
    resolve_site_updates,
    resolve_variable_updates,
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
    sensor_model_id=3,
    serial_number="OLD123",
    description="Old description",
) -> MetadataRow:
    return MetadataRow(
        database_id=17,
        values={
            "sensor_model_id": sensor_model_id,
            "serial_number": serial_number,
            "description": description,
        },
    )


def _site_update_config(
    set_values: dict[str, object],
) -> ConfigModel:
    return ConfigModel(
        updates={
            "sites": [
                {
                    "update": {
                        "site_code": "SAN",
                    },
                    "set": set_values,
                }
            ]
        }
    )


def _site_row(
    *,
    site_code="SAN",
    name="Sandhagen",
    description="Old description",
    latitude=54.10,
    longitude=13.40,
    parent_id=5,
) -> MetadataRow:
    return MetadataRow(
        database_id=11,
        values={
            "site_code": site_code,
            "name": name,
            "description": description,
            "latitude": latitude,
            "longitude": longitude,
            "parent_id": parent_id,
        },
    )


def _location_type_update_config(
    set_values: dict[str, object],
) -> ConfigModel:
    return ConfigModel(
        updates={
            "location_types": [
                {
                    "update": {
                        "type": "plot",
                    },
                    "set": set_values,
                }
            ]
        }
    )


def _location_type_row(
    *,
    type_="plot",
    description="Old description",
) -> MetadataRow:
    return MetadataRow(
        database_id=21,
        values={
            "type": type_,
            "description": description,
        },
    )


def _sensor_type_update_config(
    set_values: dict[str, object],
) -> ConfigModel:
    return ConfigModel(
        updates={
            "sensor_types": [
                {
                    "update": {
                        "type": "pressure",
                    },
                    "set": set_values,
                }
            ]
        }
    )


def _sensor_type_row(
    *,
    type_="pressure",
    description="Old description",
) -> MetadataRow:
    return MetadataRow(
        database_id=31,
        values={
            "type": type_,
            "description": description,
        },
    )


def _variable_update_config(
    set_values: dict[str, object],
) -> ConfigModel:
    return ConfigModel(
        updates={
            "variables": [
                {
                    "update": {
                        "variable": "water_level",
                    },
                    "set": set_values,
                }
            ]
        }
    )


def _variable_row(
    *,
    variable="water_level",
    derived=False,
    description="Old description",
) -> MetadataRow:
    return MetadataRow(
        database_id=41,
        values={
            "variable": variable,
            "derived": derived,
            "description": description,
        },
    )


def _sensor_type_update_config(
    set_values: dict[str, object],
) -> ConfigModel:
    return ConfigModel(
        updates={
            "sensor_types": [
                {
                    "update": {
                        "type": "pressure",
                    },
                    "set": set_values,
                }
            ]
        }
    )


def _sensor_type_row(
    *,
    type_="pressure",
    description="Old description",
) -> MetadataRow:
    return MetadataRow(
        database_id=31,
        values={
            "type": type_,
            "description": description,
        },
    )


def _location_update_config(
    set_values: dict[str, object],
) -> ConfigModel:
    return ConfigModel(
        updates={
            "locations": [
                {
                    "update": {
                        "initial_label": "tree_001",
                    },
                    "set": set_values,
                }
            ]
        }
    )


def _location_row(
    *,
    site_id=11,
    location_type_id=21,
    latitude=54.10,
    longitude=13.40,
    height_above_ground=1.30,
    azimuth=180.0,
) -> MetadataRow:
    return MetadataRow(
        database_id=71,
        values={
            "site_id": site_id,
            "location_type_id": location_type_id,
            "latitude": latitude,
            "longitude": longitude,
            "height_above_ground": height_above_ground,
            "azimuth": azimuth,
            "initial_label": "tree_001",
            "initial_label_valid_from": None,
            "initial_label_valid_to": None,
        },
    )


def _sensor_model_update_config(
    set_values: dict[str, object],
) -> ConfigModel:
    return ConfigModel(
        updates={
            "sensor_models": [
                {
                    "update": {
                        "manufacturer": "Campbell Scientific",
                        "model": "CS451",
                    },
                    "set": set_values,
                }
            ]
        }
    )


def _sensor_model_row(
    *,
    manufacturer="Campbell Scientific",
    model="CS451",
    sensor_type_id=31,
) -> MetadataRow:
    return MetadataRow(
        database_id=51,
        values={
            "manufacturer": manufacturer,
            "model": model,
            "sensor_type_id": sensor_type_id,
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


def test_site_description_change_becomes_update(
    monkeypatch,
):
    config = _site_update_config(
        {
            "description": "New description",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_site",
        lambda site_code: _site_row(),
    )

    items, errors = resolve_site_updates(config)

    assert errors == ()
    assert len(items) == 1

    item = items[0]

    assert item.plan_id == "updates.sites[0]"
    assert item.resource_type == "site"
    assert item.action == PlanAction.UPDATE
    assert item.database_id == 11

    assert len(item.changes) == 1

    change = item.changes[0]
    assert change.field == "description"
    assert change.before == "Old description"
    assert change.after == "New description"
    assert change.identity_change is False

    assert item.values.site_code == "SAN"
    assert item.values.name == "Sandhagen"
    assert item.values.description == "New description"
    assert item.values.latitude == 54.10
    assert item.values.longitude == 13.40
    assert item.values.parent == ExistingRef(
        resource_type="site",
        database_id=5,
    )


def test_site_code_change_is_identity_change(
    monkeypatch,
):
    config = _site_update_config(
        {
            "site_code": "SANDHAGEN",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_site",
        lambda site_code: _site_row(),
    )

    items, errors = resolve_site_updates(config)

    assert errors == ()
    assert len(items) == 1

    change = items[0].changes[0]

    assert change.field == "site_code"
    assert change.before == "SAN"
    assert change.after == "SANDHAGEN"
    assert change.identity_change is True

    assert items[0].requires_confirmation is True
    assert items[0].values.site_code == "SANDHAGEN"


def test_site_update_with_no_actual_change_is_noop(
    monkeypatch,
):
    config = _site_update_config(
        {
            "name": "Sandhagen",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_site",
        lambda site_code: _site_row(),
    )

    items, errors = resolve_site_updates(config)

    assert items == ()
    assert errors == ()


def test_site_update_can_clear_description(
    monkeypatch,
):
    config = _site_update_config(
        {
            "description": None,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_site",
        lambda site_code: _site_row(),
    )

    items, errors = resolve_site_updates(config)

    assert errors == ()
    assert len(items) == 1

    change = items[0].changes[0]

    assert change.field == "description"
    assert change.before == "Old description"
    assert change.after is None
    assert change.identity_change is False

    assert items[0].values.description is None


def test_site_update_propagates_not_found(
    monkeypatch,
):
    config = _site_update_config(
        {
            "description": "New description",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_site",
        lambda site_code: None,
    )

    items, errors = resolve_site_updates(config)

    assert items == ()
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.NOT_FOUND
    assert errors[0].resource_type == "site"
    assert errors[0].source_path == (
        "updates.sites[0].update"
    )


def test_site_update_accepts_single_coordinate_correction(
    monkeypatch,
):
    config = _site_update_config(
        {
            "latitude": 54.20,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_site",
        lambda site_code: _site_row(
            latitude=54.10,
            longitude=13.40,
        ),
    )

    items, errors = resolve_site_updates(config)

    assert errors == ()
    assert len(items) == 1
    assert items[0].values.latitude == 54.20
    assert items[0].values.longitude == 13.40


def test_site_update_rejects_final_coordinate_mismatch(
    monkeypatch,
):
    config = _site_update_config(
        {
            "latitude": None,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_site",
        lambda site_code: _site_row(
            latitude=54.10,
            longitude=13.40,
        ),
    )

    items, errors = resolve_site_updates(config)

    assert items == ()
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "site"
    assert errors[0].source_path == "updates.sites[0].set"


def test_site_update_rejects_setting_only_one_missing_coordinate(
    monkeypatch,
):
    config = _site_update_config(
        {
            "latitude": 54.20,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_site",
        lambda site_code: _site_row(
            latitude=None,
            longitude=None,
        ),
    )

    items, errors = resolve_site_updates(config)

    assert items == ()
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT


def test_site_update_can_clear_both_coordinates(
    monkeypatch,
):
    config = _site_update_config(
        {
            "latitude": None,
            "longitude": None,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_site",
        lambda site_code: _site_row(
            latitude=54.10,
            longitude=13.40,
        ),
    )

    items, errors = resolve_site_updates(config)

    assert errors == ()
    assert len(items) == 1
    assert items[0].values.latitude is None
    assert items[0].values.longitude is None


def test_location_type_description_change_becomes_update(
    monkeypatch,
):
    config = _location_type_update_config(
        {"description": "Monitoring plot"}
    )

    monkeypatch.setattr(
        metadata,
        "find_location_type",
        lambda type_: _location_type_row(),
    )

    items, errors = resolve_location_type_updates(config)

    assert errors == ()
    assert len(items) == 1

    item = items[0]
    assert item.resource_type == "location_type"
    assert item.database_id == 21
    assert item.changes == (
        FieldChange(
            field="description",
            before="Old description",
            after="Monitoring plot",
            identity_change=False,
        ),
    )


def test_location_type_type_change_is_identity_change(
    monkeypatch,
):
    config = _location_type_update_config(
        {"type": "monitoring_plot"}
    )

    monkeypatch.setattr(
        metadata,
        "find_location_type",
        lambda type_: _location_type_row(),
    )

    items, errors = resolve_location_type_updates(config)

    assert errors == ()
    assert items[0].changes[0].identity_change is True
    assert items[0].values.type == "monitoring_plot"
    assert items[0].requires_confirmation is True


def test_location_type_update_with_no_actual_change_is_noop(
    monkeypatch,
):
    config = _location_type_update_config(
        {"description": "Old description"}
    )

    monkeypatch.setattr(
        metadata,
        "find_location_type",
        lambda type_: _location_type_row(),
    )

    items, errors = resolve_location_type_updates(config)

    assert items == ()
    assert errors == ()


def test_location_type_update_propagates_not_found(
    monkeypatch,
):
    config = _location_type_update_config(
        {"description": "New"}
    )

    monkeypatch.setattr(
        metadata,
        "find_location_type",
        lambda type_: None,
    )

    items, errors = resolve_location_type_updates(config)

    assert items == ()
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.NOT_FOUND


def test_variable_description_change_becomes_update(monkeypatch):
    config = _variable_update_config(
        {"description": "Water-table level"}
    )

    monkeypatch.setattr(
        metadata,
        "find_variable",
        lambda variable: _variable_row(),
    )

    items, errors = resolve_variable_updates(config)

    assert errors == ()
    assert len(items) == 1
    assert items[0].changes[0].field == "description"
    assert items[0].changes[0].identity_change is False


def test_variable_name_change_is_identity_change(monkeypatch):
    config = _variable_update_config(
        {"variable": "water_table_level"}
    )

    monkeypatch.setattr(
        metadata,
        "find_variable",
        lambda variable: _variable_row(),
    )

    items, errors = resolve_variable_updates(config)

    assert errors == ()
    assert items[0].changes[0].field == "variable"
    assert items[0].changes[0].identity_change is True
    assert items[0].requires_confirmation is True


def test_variable_update_can_change_derived(monkeypatch):
    config = _variable_update_config(
        {"derived": True}
    )

    monkeypatch.setattr(
        metadata,
        "find_variable",
        lambda variable: _variable_row(
            derived=False,
        ),
    )

    items, errors = resolve_variable_updates(config)

    assert errors == ()
    assert items[0].values.derived is True


def test_variable_update_can_clear_description(monkeypatch):
    config = _variable_update_config(
        {"description": None}
    )

    monkeypatch.setattr(
        metadata,
        "find_variable",
        lambda variable: _variable_row(),
    )

    items, errors = resolve_variable_updates(config)

    assert errors == ()
    assert items[0].values.description is None


def test_variable_update_with_no_actual_change_is_noop(
    monkeypatch,
):
    config = _variable_update_config(
        {"derived": False}
    )

    monkeypatch.setattr(
        metadata,
        "find_variable",
        lambda variable: _variable_row(
            derived=False,
        ),
    )

    items, errors = resolve_variable_updates(config)

    assert items == ()
    assert errors == ()


def test_sensor_type_description_change_becomes_update(
    monkeypatch,
):
    config = _sensor_type_update_config(
        {
            "description": "Pressure transducer",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_type",
        lambda type_: _sensor_type_row(),
    )

    items, errors = resolve_sensor_type_updates(config)

    assert errors == ()
    assert len(items) == 1

    item = items[0]

    assert item.plan_id == "updates.sensor_types[0]"
    assert item.resource_type == "sensor_type"
    assert item.action == PlanAction.UPDATE
    assert item.database_id == 31

    assert item.changes == (
        FieldChange(
            field="description",
            before="Old description",
            after="Pressure transducer",
            identity_change=False,
        ),
    )

    assert item.values.type == "pressure"
    assert item.values.description == "Pressure transducer"
    assert item.requires_confirmation is False


def test_sensor_type_type_change_is_identity_change(
    monkeypatch,
):
    config = _sensor_type_update_config(
        {
            "type": "pressure_transducer",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_type",
        lambda type_: _sensor_type_row(),
    )

    items, errors = resolve_sensor_type_updates(config)

    assert errors == ()
    assert len(items) == 1

    item = items[0]
    change = item.changes[0]

    assert change.field == "type"
    assert change.before == "pressure"
    assert change.after == "pressure_transducer"
    assert change.identity_change is True

    assert item.values.type == "pressure_transducer"
    assert item.values.description == "Old description"
    assert item.requires_confirmation is True


def test_sensor_type_update_with_no_actual_change_is_noop(
    monkeypatch,
):
    config = _sensor_type_update_config(
        {
            "description": "Old description",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_type",
        lambda type_: _sensor_type_row(),
    )

    items, errors = resolve_sensor_type_updates(config)

    assert items == ()
    assert errors == ()


def test_sensor_type_update_can_clear_description(
    monkeypatch,
):
    config = _sensor_type_update_config(
        {
            "description": None,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_type",
        lambda type_: _sensor_type_row(),
    )

    items, errors = resolve_sensor_type_updates(config)

    assert errors == ()
    assert len(items) == 1

    change = items[0].changes[0]

    assert change.field == "description"
    assert change.before == "Old description"
    assert change.after is None
    assert change.identity_change is False

    assert items[0].values.description is None


def test_sensor_type_update_propagates_not_found(
    monkeypatch,
):
    config = _sensor_type_update_config(
        {
            "description": "Pressure transducer",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_type",
        lambda type_: None,
    )

    items, errors = resolve_sensor_type_updates(config)

    assert items == ()
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.NOT_FOUND
    assert errors[0].resource_type == "sensor_type"
    assert errors[0].source_path == (
        "updates.sensor_types[0].update"
    )


def test_sensor_model_manufacturer_change_is_identity_change(
    monkeypatch,
):
    config = _sensor_model_update_config(
        {
            "manufacturer": "Campbell Scientific Inc.",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (_sensor_model_row(),),
    )

    items, errors = resolve_sensor_model_updates(config)

    assert errors == ()
    assert len(items) == 1

    item = items[0]

    assert item.plan_id == "updates.sensor_models[0]"
    assert item.resource_type == "sensor_model"
    assert item.action == PlanAction.UPDATE
    assert item.database_id == 51

    assert item.changes == (
        FieldChange(
            field="manufacturer",
            before="Campbell Scientific",
            after="Campbell Scientific Inc.",
            identity_change=True,
        ),
    )

    assert item.values.manufacturer == "Campbell Scientific Inc."
    assert item.values.model == "CS451"
    assert item.values.sensor_type == ExistingRef(
        resource_type="sensor_type",
        database_id=31,
    )
    assert item.requires_confirmation is True


def test_sensor_model_model_change_is_identity_change(
    monkeypatch,
):
    config = _sensor_model_update_config(
        {
            "model": "CS451-L",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (_sensor_model_row(),),
    )

    items, errors = resolve_sensor_model_updates(config)

    assert errors == ()
    assert len(items) == 1

    change = items[0].changes[0]

    assert change.field == "model"
    assert change.before == "CS451"
    assert change.after == "CS451-L"
    assert change.identity_change is True


def test_sensor_model_sensor_type_change_is_not_identity_change(
    monkeypatch,
):
    config = _sensor_model_update_config(
        {
            "sensor_type": "water_pressure",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (_sensor_model_row(),),
    )

    bindings = (
        PlanBinding(
            resource_type="sensor_types",
            alias="water_pressure",
            resource=ExistingRef(
                resource_type="sensor_type",
                database_id=32,
            ),
        ),
    )

    items, errors = resolve_sensor_model_updates(
        config,
        existing_bindings=bindings,
    )

    assert errors == ()
    assert len(items) == 1

    change = items[0].changes[0]

    assert change.field == "sensor_type"
    assert change.before == ExistingRef(
        resource_type="sensor_type",
        database_id=31,
    )
    assert change.after == ExistingRef(
        resource_type="sensor_type",
        database_id=32,
    )
    assert change.identity_change is False

    assert items[0].values.sensor_type == ExistingRef(
        resource_type="sensor_type",
        database_id=32,
    )
    assert items[0].requires_confirmation is False


def test_sensor_model_sensor_type_can_use_planned_ref(
    monkeypatch,
):
    config = _sensor_model_update_config(
        {
            "sensor_type": "new_pressure_type",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (_sensor_model_row(),),
    )

    planned = PlannedRef(
        resource_type="sensor_type",
        plan_id="sensor_types[0]",
    )

    bindings = (
        PlanBinding(
            resource_type="sensor_types",
            alias="new_pressure_type",
            resource=planned,
        ),
    )

    items, errors = resolve_sensor_model_updates(
        config,
        existing_bindings=bindings,
    )

    assert errors == ()
    assert len(items) == 1
    assert items[0].changes[0].after == planned
    assert items[0].values.sensor_type == planned


def test_sensor_model_update_reports_invalid_sensor_type_reference(
    monkeypatch,
):
    config = _sensor_model_update_config(
        {
            "sensor_type": "missing_type",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (_sensor_model_row(),),
    )

    items, errors = resolve_sensor_model_updates(
        config,
        existing_bindings=(),
    )

    assert items == ()
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.INVALID_REFERENCE
    assert errors[0].resource_type == "sensor_model"
    assert errors[0].source_path == (
        "updates.sensor_models[0].set.sensor_type"
    )


def test_sensor_model_update_with_no_actual_change_is_noop(
    monkeypatch,
):
    config = _sensor_model_update_config(
        {
            "manufacturer": "Campbell Scientific",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (_sensor_model_row(),),
    )

    items, errors = resolve_sensor_model_updates(config)

    assert items == ()
    assert errors == ()


def test_location_height_change_becomes_update(
    monkeypatch,
):
    config = _location_update_config(
        {
            "height_above_ground": 1.50,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (_location_row(),),
    )

    items, errors = resolve_location_updates(config)

    assert errors == ()
    assert len(items) == 1

    item = items[0]

    assert item.plan_id == "updates.locations[0]"
    assert item.resource_type == "location"
    assert item.action == PlanAction.UPDATE
    assert item.database_id == 71

    assert item.changes == (
        FieldChange(
            field="height_above_ground",
            before=1.30,
            after=1.50,
            identity_change=False,
        ),
    )

    assert item.values.site == ExistingRef(
        resource_type="site",
        database_id=11,
    )
    assert item.values.location_type == ExistingRef(
        resource_type="location_type",
        database_id=21,
    )
    assert item.values.height_above_ground == 1.50
    assert item.requires_confirmation is False


def test_location_site_change_is_identity_change(
    monkeypatch,
):
    config = _location_update_config(
        {
            "site": "new_site",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (_location_row(),),
    )

    new_site = ExistingRef(
        resource_type="site",
        database_id=12,
    )

    bindings = (
        PlanBinding(
            resource_type="sites",
            alias="new_site",
            resource=new_site,
        ),
    )

    items, errors = resolve_location_updates(
        config,
        existing_bindings=bindings,
    )

    assert errors == ()
    assert len(items) == 1

    change = items[0].changes[0]

    assert change.field == "site"
    assert change.before == ExistingRef(
        resource_type="site",
        database_id=11,
    )
    assert change.after == new_site
    assert change.identity_change is True

    assert items[0].values.site == new_site
    assert items[0].requires_confirmation is True


def test_location_type_change_is_not_identity_change(
    monkeypatch,
):
    config = _location_update_config(
        {
            "location_type": "stem",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (_location_row(),),
    )

    new_type = ExistingRef(
        resource_type="location_type",
        database_id=22,
    )

    bindings = (
        PlanBinding(
            resource_type="location_types",
            alias="stem",
            resource=new_type,
        ),
    )

    items, errors = resolve_location_updates(
        config,
        existing_bindings=bindings,
    )

    assert errors == ()
    assert len(items) == 1

    change = items[0].changes[0]

    assert change.field == "location_type"
    assert change.before == ExistingRef(
        resource_type="location_type",
        database_id=21,
    )
    assert change.after == new_type
    assert change.identity_change is False
    assert items[0].requires_confirmation is False


def test_location_site_can_use_planned_ref(
    monkeypatch,
):
    config = _location_update_config(
        {
            "site": "future_site",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (_location_row(),),
    )

    planned = PlannedRef(
        resource_type="site",
        plan_id="sites[0]",
    )

    bindings = (
        PlanBinding(
            resource_type="sites",
            alias="future_site",
            resource=planned,
        ),
    )

    items, errors = resolve_location_updates(
        config,
        existing_bindings=bindings,
    )

    assert errors == ()
    assert items[0].changes[0].after == planned
    assert items[0].changes[0].identity_change is True
    assert items[0].values.site == planned


def test_location_update_reports_invalid_site_reference(
    monkeypatch,
):
    config = _location_update_config(
        {
            "site": "missing_site",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (_location_row(),),
    )

    items, errors = resolve_location_updates(
        config,
        existing_bindings=(),
    )

    assert items == ()
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.INVALID_REFERENCE
    assert errors[0].resource_type == "location"
    assert errors[0].source_path == (
        "updates.locations[0].set.site"
    )


def test_location_update_with_no_actual_change_is_noop(
    monkeypatch,
):
    config = _location_update_config(
        {
            "azimuth": 180.0,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (_location_row(),),
    )

    items, errors = resolve_location_updates(config)

    assert items == ()
    assert errors == ()


def test_location_update_accepts_single_coordinate_correction(
    monkeypatch,
):
    config = _location_update_config(
        {
            "latitude": 54.20,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (
            _location_row(
                latitude=54.10,
                longitude=13.40,
            ),
        ),
    )

    items, errors = resolve_location_updates(config)

    assert errors == ()
    assert len(items) == 1
    assert items[0].values.latitude == 54.20
    assert items[0].values.longitude == 13.40


def test_location_update_rejects_final_coordinate_mismatch(
    monkeypatch,
):
    config = _location_update_config(
        {
            "latitude": None,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (
            _location_row(
                latitude=54.10,
                longitude=13.40,
            ),
        ),
    )

    items, errors = resolve_location_updates(config)

    assert items == ()
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "location"
    assert errors[0].source_path == "updates.locations[0].set"


def test_location_update_rejects_setting_only_one_missing_coordinate(
    monkeypatch,
):
    config = _location_update_config(
        {
            "latitude": 54.20,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (
            _location_row(
                latitude=None,
                longitude=None,
            ),
        ),
    )

    items, errors = resolve_location_updates(config)

    assert items == ()
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT


def test_location_update_can_clear_both_coordinates(
    monkeypatch,
):
    config = _location_update_config(
        {
            "latitude": None,
            "longitude": None,
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (
            _location_row(
                latitude=54.10,
                longitude=13.40,
            ),
        ),
    )

    items, errors = resolve_location_updates(config)

    assert errors == ()
    assert len(items) == 1
    assert items[0].values.latitude is None
    assert items[0].values.longitude is None


def test_sensor_model_change_is_identity_change(
    monkeypatch,
):
    config = _sensor_update_config(
        {
            "sensor_model": "replacement_model",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (_sensor_row(),),
    )

    replacement = ExistingRef(
        resource_type="sensor_model",
        database_id=4,
    )

    bindings = (
        PlanBinding(
            resource_type="sensor_models",
            alias="replacement_model",
            resource=replacement,
        ),
    )

    items, errors = resolve_sensor_updates(
        config,
        existing_bindings=bindings,
    )

    assert errors == ()
    assert len(items) == 1

    item = items[0]
    change = item.changes[0]

    assert change.field == "sensor_model"
    assert change.before == ExistingRef(
        resource_type="sensor_model",
        database_id=3,
    )
    assert change.after == replacement
    assert change.identity_change is True

    assert item.values.sensor_model == replacement
    assert item.requires_confirmation is True


def test_sensor_model_change_can_use_planned_ref(
    monkeypatch,
):
    config = _sensor_update_config(
        {
            "sensor_model": "new_model",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (_sensor_row(),),
    )

    planned = PlannedRef(
        resource_type="sensor_model",
        plan_id="sensor_models[0]",
    )

    bindings = (
        PlanBinding(
            resource_type="sensor_models",
            alias="new_model",
            resource=planned,
        ),
    )

    items, errors = resolve_sensor_updates(
        config,
        existing_bindings=bindings,
    )

    assert errors == ()
    assert len(items) == 1

    change = items[0].changes[0]

    assert change.before == ExistingRef(
        resource_type="sensor_model",
        database_id=3,
    )
    assert change.after == planned
    assert change.identity_change is True
    assert items[0].values.sensor_model == planned


def test_sensor_model_change_missing_binding_is_invalid(
    monkeypatch,
):
    config = _sensor_update_config(
        {
            "sensor_model": "missing_model",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (_sensor_row(),),
    )

    items, errors = resolve_sensor_updates(
        config,
        existing_bindings=(),
    )

    assert items == ()
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.INVALID_REFERENCE
    assert errors[0].resource_type == "sensor"
    assert errors[0].source_path == (
        "updates.sensors[0].set.sensor_model"
    )


def test_sensor_model_change_to_current_model_is_noop(
    monkeypatch,
):
    config = _sensor_update_config(
        {
            "sensor_model": "current_model",
        }
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (_sensor_row(),),
    )

    bindings = (
        PlanBinding(
            resource_type="sensor_models",
            alias="current_model",
            resource=ExistingRef(
                resource_type="sensor_model",
                database_id=3,
            ),
        ),
    )

    items, errors = resolve_sensor_updates(
        config,
        existing_bindings=bindings,
    )

    assert items == ()
    assert errors == ()

