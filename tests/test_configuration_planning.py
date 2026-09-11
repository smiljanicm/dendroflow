from dendroflow.configuration import metadata as metadata_db
from dendroflow.configuration import raw as raw_db
from dendroflow.configuration.metadata import MetadataRow
from dendroflow.configuration.parser import load_config
from dendroflow.configuration.plan import (
    ExistingRef,
    PlanAction,
    PlanErrorCode,
    PlannedRef,
    ResolvedDeploymentValues,
    ResolvedFileValues,
    ResolvedInterfaceValues,
    ResolvedSensorValues,
)
from dendroflow.configuration.resolution.orchestration import (
    resolve_config,
)


def test_mixed_yaml_builds_applicable_plan(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sites:
  - ref: new_site
    site_code: TEST01
    name: Test Site

references:
  deployments:
    water_level_main:
      valid_from: "2025-01-01T00:00:00+00:00"

files:
  - ref: water_table_file
    path: tests/data/example.csv
    timestamp:
      timezone: Etc/GMT-1
      format: "%Y-%m-%d %H:%M:%S"
    reader:
      type: csv
      options:
        delimiter: ","
    interfaces:
      - deployment: water_level_main
        timestamp_column: TIMESTAMP
        values_column: Lvl_cm_Avg
        unit: cm
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        metadata_db,
        "find_site",
        lambda site_code: None,
    )

    def fake_find_deployments(
        *,
        sensor_id=None,
        location_id=None,
        variable_id=None,
        valid_from=None,
    ):
        assert sensor_id is None
        assert location_id is None
        assert variable_id is None

        if valid_from is None:
            return ()

        return (
            MetadataRow(
                database_id=41,
                values={
                    "sensor_id": 11,
                    "location_id": 21,
                    "variable_id": 31,
                    "valid_from": valid_from,
                    "valid_to": None,
                },
            ),
        )

    monkeypatch.setattr(
        metadata_db,
        "find_deployments",
        fake_find_deployments,
    )

    monkeypatch.setattr(
        raw_db,
        "find_file",
        lambda filepath: None,
    )

    config = load_config(config_path)
    plan = resolve_config(config)

    assert plan.errors == ()
    assert plan.can_apply is True
    assert plan.requires_confirmation is False

    assert tuple(
        item.plan_id
        for item in plan.metadata_items
    ) == (
        "sites[0]",
    )

    assert tuple(
        item.plan_id
        for item in plan.raw_items
    ) == (
        "files[0]",
        "files[0].interfaces[0]",
    )

    site_item = plan.metadata_items[0]

    assert site_item.resource_type == "site"
    assert site_item.action == PlanAction.CREATE
    assert site_item.database_id is None

    file_item = plan.raw_items[0]

    assert file_item.resource_type == "file"
    assert file_item.action == PlanAction.CREATE
    assert file_item.database_id is None
    assert isinstance(
        file_item.values,
        ResolvedFileValues,
    )
    assert file_item.values.filepath == (
        "tests/data/example.csv"
    )
    assert file_item.values.reader_config == {
        "reader": "csv",
        "options": {
            "delimiter": ",",
        },
    }

    interface_item = plan.raw_items[1]

    assert interface_item.resource_type == "interface"
    assert interface_item.action == PlanAction.CREATE
    assert isinstance(
        interface_item.values,
        ResolvedInterfaceValues,
    )

    assert interface_item.values.file == PlannedRef(
        resource_type="file",
        plan_id="files[0]",
    )
    assert interface_item.values.deployment == ExistingRef(
        resource_type="deployment",
        database_id=41,
    )

    assert tuple(
        binding.alias
        for binding in plan.bindings
    ) == (
        "new_site",
        "water_level_main",
        "water_table_file",
    )


def test_planned_dependency_chain_reaches_raw_interface(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
references:
  variables:
    water_level:
      variable: water_level

  sensor_models:
    pressure_model:
      manufacturer: Acme
      model: WL-100

  locations:
    well_a:
      initial_label: Well A

sensors:
  - ref: new_sensor
    serial_number: SENSOR-001
    sensor_model: pressure_model

deployments:
  - ref: new_deployment
    sensor: new_sensor
    location: well_a
    variable: water_level
    valid_from: "2025-01-01T00:00:00+00:00"

files:
  - ref: water_table_file
    path: tests/data/example.csv
    timestamp:
      timezone: Etc/GMT-1
      format: "%Y-%m-%d %H:%M:%S"
    reader:
      type: csv
      options:
        delimiter: ","
    interfaces:
      - deployment: new_deployment
        timestamp_column: TIMESTAMP
        values_column: Lvl_cm_Avg
        unit: cm
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        metadata_db,
        "find_variable",
        lambda variable: MetadataRow(
            database_id=31,
            values={
                "variable": variable,
                "derived": False,
                "description": None,
            },
        ),
    )

    monkeypatch.setattr(
        metadata_db,
        "find_sensor_models",
        lambda **kwargs: (
            MetadataRow(
                database_id=3,
                values={
                    "model": "WL-100",
                    "manufacturer": "Acme",
                    "sensor_type_id": 7,
                },
            ),
        ),
    )

    monkeypatch.setattr(
        metadata_db,
        "find_sensors",
        lambda **kwargs: (),
    )

    monkeypatch.setattr(
        metadata_db,
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
                    "initial_label": "Well A",
                    "initial_label_valid_from": None,
                    "initial_label_valid_to": None,
                },
            ),
        ),
    )

    monkeypatch.setattr(
        raw_db,
        "find_file",
        lambda filepath: None,
    )

    config = load_config(config_path)
    plan = resolve_config(config)

    assert plan.errors == ()
    assert plan.can_apply is True
    assert plan.requires_confirmation is False

    assert tuple(
        item.plan_id
        for item in plan.metadata_items
    ) == (
        "sensors[0]",
        "deployments[0]",
    )

    sensor_item = plan.metadata_items[0]

    assert sensor_item.action == PlanAction.CREATE
    assert sensor_item.resource_type == "sensor"
    assert isinstance(
        sensor_item.values,
        ResolvedSensorValues,
    )
    assert sensor_item.values.sensor_model == ExistingRef(
        resource_type="sensor_model",
        database_id=3,
    )

    deployment_item = plan.metadata_items[1]

    assert deployment_item.action == PlanAction.CREATE
    assert deployment_item.resource_type == "deployment"
    assert isinstance(
        deployment_item.values,
        ResolvedDeploymentValues,
    )

    assert deployment_item.values.sensor == PlannedRef(
        resource_type="sensor",
        plan_id="sensors[0]",
    )
    assert deployment_item.values.location == ExistingRef(
        resource_type="location",
        database_id=21,
    )
    assert deployment_item.values.variable == ExistingRef(
        resource_type="variable",
        database_id=31,
    )

    assert tuple(
        item.plan_id
        for item in plan.raw_items
    ) == (
        "files[0]",
        "files[0].interfaces[0]",
    )

    interface_item = plan.raw_items[1]

    assert isinstance(
        interface_item.values,
        ResolvedInterfaceValues,
    )

    assert interface_item.values.file == PlannedRef(
        resource_type="file",
        plan_id="files[0]",
    )
    assert interface_item.values.deployment == PlannedRef(
        resource_type="deployment",
        plan_id="deployments[0]",
    )

    assert tuple(
        binding.alias
        for binding in plan.bindings
    ) == (
        "water_level",
        "pressure_model",
        "new_sensor",
        "well_a",
        "new_deployment",
        "water_table_file",
    )


def test_sensor_identity_update_from_yaml_requires_confirmation(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
updates:
  sensors:
    - update:
        serial_number: OLD123
      set:
        serial_number: NEW123
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        metadata_db,
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

    config = load_config(config_path)
    plan = resolve_config(config)

    assert plan.errors == ()
    assert plan.can_apply is True
    assert plan.requires_confirmation is True

    assert len(plan.metadata_items) == 1
    assert plan.raw_items == ()

    item = plan.metadata_items[0]

    assert item.plan_id == "updates.sensors[0]"
    assert item.resource_type == "sensor"
    assert item.action == PlanAction.UPDATE
    assert item.database_id == 17

    assert isinstance(
        item.values,
        ResolvedSensorValues,
    )

    assert item.values.sensor_model == ExistingRef(
        resource_type="sensor_model",
        database_id=3,
    )
    assert item.values.serial_number == "NEW123"
    assert item.values.description is None

    assert len(item.changes) == 1

    change = item.changes[0]

    assert change.field == "serial_number"
    assert change.before == "OLD123"
    assert change.after == "NEW123"
    assert change.identity_change is True

    assert item.requires_confirmation is True


def test_independent_raw_branch_survives_metadata_resolution_error(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
references:
  sites:
    missing_site:
      site_code: DOES_NOT_EXIST

  deployments:
    existing_deployment:
      valid_from: "2025-01-01T00:00:00+00:00"

files:
  - ref: independent_file
    path: tests/data/example.csv
    timestamp:
      timezone: Etc/GMT-1
      format: "%Y-%m-%d %H:%M:%S"
    reader:
      type: csv
      options:
        delimiter: ","
    interfaces:
      - deployment: existing_deployment
        timestamp_column: TIMESTAMP
        values_column: Lvl_cm_Avg
        unit: cm
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        metadata_db,
        "find_site",
        lambda site_code: None,
    )

    monkeypatch.setattr(
        metadata_db,
        "find_deployments",
        lambda **kwargs: (
            MetadataRow(
                database_id=41,
                values={
                    "sensor_id": 11,
                    "location_id": 21,
                    "variable_id": 31,
                    "valid_from": kwargs["valid_from"],
                    "valid_to": None,
                },
            ),
        ),
    )

    monkeypatch.setattr(
        raw_db,
        "find_file",
        lambda filepath: None,
    )

    config = load_config(config_path)
    plan = resolve_config(config)

    assert plan.can_apply is False

    assert len(plan.errors) == 1
    assert plan.errors[0].code == PlanErrorCode.NOT_FOUND
    assert plan.errors[0].resource_type == "sites"

    assert tuple(
        item.plan_id
        for item in plan.raw_items
    ) == (
        "files[0]",
        "files[0].interfaces[0]",
    )

    file_item = plan.raw_items[0]
    interface_item = plan.raw_items[1]

    assert file_item.action == PlanAction.CREATE
    assert interface_item.action == PlanAction.CREATE

    assert isinstance(
        interface_item.values,
        ResolvedInterfaceValues,
    )
    assert interface_item.values.deployment == ExistingRef(
        resource_type="deployment",
        database_id=41,
    )


