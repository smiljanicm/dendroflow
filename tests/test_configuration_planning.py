from datetime import datetime, timezone

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
from dendroflow.configuration.resolution import orchestration
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


def test_deployment_update_conflicting_with_persisted_history_is_not_applicable(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
updates:
  deployments:
    - update:
        valid_from: "2025-01-01T00:00:00+00:00"
      set:
        valid_from: "2025-03-01T00:00:00+00:00"
        valid_to: "2025-05-01T00:00:00+00:00"
""",
        encoding="utf-8",
    )

    def fake_find_deployments(**kwargs):
        # Selector lookup for the deployment being updated.
        if kwargs.get("valid_from") is not None:
            return (
                MetadataRow(
                    database_id=41,
                    values={
                        "sensor_id": 11,
                        "location_id": 21,
                        "variable_id": 31,
                        "valid_from": datetime(
                            2025,
                            1,
                            1,
                            tzinfo=timezone.utc,
                        ),
                        "valid_to": datetime(
                            2025,
                            2,
                            1,
                            tzinfo=timezone.utc,
                        ),
                    },
                ),
            )

        # Persisted-history lookup for sensor 11 / variable 31.
        assert kwargs.get("sensor_id") == 11
        assert kwargs.get("variable_id") == 31

        return (
            # The row being updated: D7 must ignore this one.
            MetadataRow(
                database_id=41,
                values={
                    "sensor_id": 11,
                    "location_id": 21,
                    "variable_id": 31,
                    "valid_from": datetime(
                        2025,
                        1,
                        1,
                        tzinfo=timezone.utc,
                    ),
                    "valid_to": datetime(
                        2025,
                        2,
                        1,
                        tzinfo=timezone.utc,
                    ),
                },
            ),
            # Untouched persisted deployment that conflicts
            # with the requested final interval.
            MetadataRow(
                database_id=42,
                values={
                    "sensor_id": 11,
                    "location_id": 22,
                    "variable_id": 31,
                    "valid_from": datetime(
                        2025,
                        4,
                        1,
                        tzinfo=timezone.utc,
                    ),
                    "valid_to": datetime(
                        2025,
                        6,
                        1,
                        tzinfo=timezone.utc,
                    ),
                },
            ),
        )

    monkeypatch.setattr(
        metadata_db,
        "find_deployments",
        fake_find_deployments,
    )

    monkeypatch.setattr(
        orchestration,
        "find_deployments",
        fake_find_deployments,
    )

    config = load_config(config_path)
    plan = resolve_config(config)

    # The UPDATE itself resolved successfully.
    assert len(plan.metadata_items) == 1

    item = plan.metadata_items[0]

    assert item.plan_id == "updates.deployments[0]"
    assert item.resource_type == "deployment"
    assert item.action == PlanAction.UPDATE
    assert item.database_id == 41

    assert isinstance(
        item.values,
        ResolvedDeploymentValues,
    )
    assert item.values.valid_from == datetime(
        2025,
        3,
        1,
        tzinfo=timezone.utc,
    )
    assert item.values.valid_to == datetime(
        2025,
        5,
        1,
        tzinfo=timezone.utc,
    )

    # Changing valid_from is an identity change.
    assert item.requires_confirmation is True
    assert plan.requires_confirmation is True

    # But D7 rejects the final state because it overlaps
    # untouched deployment_id 42.
    assert len(plan.errors) == 1

    error = plan.errors[0]

    assert error.code == PlanErrorCode.CONFLICT
    assert error.resource_type == "deployment"
    assert error.source_path == "updates.deployments[0]"

    assert plan.can_apply is False


def test_sandhagen_file_config_builds_expected_raw_plan(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
references:
  deployments:
    water_level_main:
      valid_from: "2025-01-01T00:00:00+00:00"

files:
  - ref: sandhagen_water_table
    path: tests/data/Sandhagen_Rewetted_WaterTbl.dat
    timestamp:
      timezone: Etc/GMT-1
      format: "%Y-%m-%d %H:%M:%S"
    reader:
      type: csv
      options:
        skiprows: [0, 2, 3]
        delimiter: ","
        encoding: utf-8
        na_values: [NAN]
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

    assert plan.errors == ()
    assert plan.can_apply is True
    assert plan.requires_confirmation is False

    assert plan.metadata_items == ()

    assert tuple(
        item.plan_id
        for item in plan.raw_items
    ) == (
        "files[0]",
        "files[0].interfaces[0]",
    )

    file_item = plan.raw_items[0]

    assert file_item.resource_type == "file"
    assert file_item.action == PlanAction.CREATE

    assert isinstance(
        file_item.values,
        ResolvedFileValues,
    )

    assert file_item.values.filepath == (
        "tests/data/Sandhagen_Rewetted_WaterTbl.dat"
    )
    assert file_item.values.timestamp_timezone == (
        "Etc/GMT-1"
    )
    assert file_item.values.timestamp_format == (
        "%Y-%m-%d %H:%M:%S"
    )

    assert file_item.values.reader_config == {
        "reader": "csv",
        "options": {
            "skiprows": [0, 2, 3],
            "delimiter": ",",
            "encoding": "utf-8",
            "na_values": ["NAN"],
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
    assert interface_item.values.timestamp_column == "TIMESTAMP"
    assert interface_item.values.values_column == "Lvl_cm_Avg"
    assert interface_item.values.unit == "cm"

    assert tuple(
        binding.alias
        for binding in plan.bindings
    ) == (
        "water_level_main",
        "sandhagen_water_table",
    )


def test_config_planning_is_deterministic(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
references:
  deployments:
    water_level_main:
      valid_from: "2025-01-01T00:00:00+00:00"

sites:
  - ref: new_site
    site_code: TEST01
    name: Test Site

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

    first = resolve_config(config)
    second = resolve_config(config)

    assert first == second

    assert first.can_apply is True
    assert first.errors == ()

    assert tuple(
        item.plan_id
        for item in first.items
    ) == (
        "sites[0]",
        "files[0]",
        "files[0].interfaces[0]",
    )

    assert tuple(
        binding.alias
        for binding in first.bindings
    ) == (
        "new_site",
        "water_level_main",
        "water_table_file",
    )


def test_mixed_plan_preserves_actions_confirmation_and_order(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
references:
  deployments:
    existing_deployment:
      valid_from: "2025-01-01T00:00:00+00:00"

sites:
  - ref: new_site
    site_code: TEST01
    name: Test Site

updates:
  sensors:
    - update:
        serial_number: OLD123
      set:
        serial_number: NEW123

files:
  - ref: new_file
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

    assert plan.errors == ()
    assert plan.can_apply is True
    assert plan.requires_confirmation is True

    assert tuple(
        (item.plan_id, item.action)
        for item in plan.metadata_items
    ) == (
        ("sites[0]", PlanAction.CREATE),
        ("updates.sensors[0]", PlanAction.UPDATE),
    )

    assert tuple(
        (item.plan_id, item.action)
        for item in plan.raw_items
    ) == (
        ("files[0]", PlanAction.CREATE),
        (
            "files[0].interfaces[0]",
            PlanAction.CREATE,
        ),
    )

    update_item = plan.metadata_items[1]

    assert update_item.database_id == 17
    assert update_item.requires_confirmation is True

    assert tuple(
        binding.alias
        for binding in plan.bindings
    ) == (
        "new_site",
        "existing_deployment",
        "new_file",
    )


def test_planned_sensor_deployment_skips_persisted_history_lookup(
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

    def fail_history_lookup(**kwargs):
        raise AssertionError(
            "persisted deployment history should not "
            "be queried for a planned sensor"
        )

    monkeypatch.setattr(
        orchestration,
        "find_deployments",
        fail_history_lookup,
    )

    config = load_config(config_path)
    plan = resolve_config(config)

    assert plan.errors == ()
    assert plan.can_apply is True

    deployment = plan.metadata_items[1]

    assert isinstance(
        deployment.values,
        ResolvedDeploymentValues,
    )
    assert deployment.values.sensor == PlannedRef(
        resource_type="sensor",
        plan_id="sensors[0]",
    )

