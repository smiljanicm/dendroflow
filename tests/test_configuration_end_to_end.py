from dendroflow.configuration import load_config, metadata
from dendroflow.configuration.metadata import MetadataRow
from dendroflow.configuration.plan import (
    ExistingRef,
    FieldChange,
    PlanAction,
    PlanErrorCode,
    PlannedRef,
)
from dendroflow.configuration.resolution.orchestration import (
    resolve_config,
)


def test_yaml_site_name_correction_becomes_update(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
updates:
  sites:
    - update:
        site_code: SITE_A
      set:
        name: New name
""",
        encoding="utf-8",
    )

    def fake_find_site(site_code):
        assert site_code == "SITE_A"

        return MetadataRow(
            database_id=11,
            values={
                "site_code": "SITE_A",
                "name": "Old name",
                "description": None,
                "latitude": None,
                "longitude": None,
                "parent_id": None,
            },
        )

    monkeypatch.setattr(
        metadata,
        "find_site",
        fake_find_site,
    )

    config = load_config(config_path)
    plan = resolve_config(config)

    assert plan.errors == ()
    assert plan.raw_items == ()
    assert len(plan.metadata_items) == 1

    item = plan.metadata_items[0]

    assert item.plan_id == "updates.sites[0]"
    assert item.resource_type == "site"
    assert item.action == PlanAction.UPDATE
    assert item.database_id == 11

    assert item.values.site_code == "SITE_A"
    assert item.values.name == "New name"

    assert item.changes == (
        FieldChange(
            field="name",
            before="Old name",
            after="New name",
            identity_change=False,
        ),
    )
    assert item.requires_confirmation is False


def test_yaml_site_code_correction_requires_confirmation(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
updates:
  sites:
    - update:
        site_code: SITE_A
      set:
        site_code: SITE_B
""",
        encoding="utf-8",
    )

    def fake_find_site(site_code):
        assert site_code == "SITE_A"

        return MetadataRow(
            database_id=11,
            values={
                "site_code": "SITE_A",
                "name": "Existing site",
                "description": None,
                "latitude": None,
                "longitude": None,
                "parent_id": None,
            },
        )

    monkeypatch.setattr(
        metadata,
        "find_site",
        fake_find_site,
    )

    config = load_config(config_path)
    plan = resolve_config(config)

    assert plan.errors == ()
    assert plan.raw_items == ()
    assert len(plan.metadata_items) == 1

    item = plan.metadata_items[0]

    assert item.plan_id == "updates.sites[0]"
    assert item.resource_type == "site"
    assert item.action == PlanAction.UPDATE
    assert item.database_id == 11

    assert item.values.site_code == "SITE_B"
    assert item.values.name == "Existing site"

    assert item.changes == (
        FieldChange(
            field="site_code",
            before="SITE_A",
            after="SITE_B",
            identity_change=True,
        ),
    )
    assert item.requires_confirmation is True


def test_yaml_site_code_correction_conflicts_with_reused_site(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sites:
  - site_code: SITE_B
    name: Destination site

updates:
  sites:
    - update:
        site_code: SITE_A
      set:
        site_code: SITE_B
""",
        encoding="utf-8",
    )

    def fake_find_site(site_code):
        rows = {
            "SITE_A": MetadataRow(
                database_id=11,
                values={
                    "site_code": "SITE_A",
                    "name": "Original site",
                    "description": None,
                    "latitude": None,
                    "longitude": None,
                    "parent_id": None,
                },
            ),
            "SITE_B": MetadataRow(
                database_id=12,
                values={
                    "site_code": "SITE_B",
                    "name": "Destination site",
                    "description": None,
                    "latitude": None,
                    "longitude": None,
                    "parent_id": None,
                },
            ),
        }
        return rows[site_code]

    monkeypatch.setattr(
        metadata,
        "find_site",
        fake_find_site,
    )

    config = load_config(config_path)
    plan = resolve_config(config)

    assert plan.raw_items == ()
    assert len(plan.metadata_items) == 2

    items = {
        item.plan_id: item
        for item in plan.metadata_items
    }

    reused = items["sites[0]"]
    updated = items["updates.sites[0]"]

    assert reused.action == PlanAction.REUSE
    assert reused.database_id == 12
    assert reused.values.site_code == "SITE_B"

    assert updated.action == PlanAction.UPDATE
    assert updated.database_id == 11
    assert updated.values.site_code == "SITE_B"
    assert updated.requires_confirmation is True

    assert len(plan.errors) == 1

    error = plan.errors[0]

    assert error.code == PlanErrorCode.CONFLICT
    assert error.resource_type == "site"
    assert error.source_path == "updates.sites[0]"
    assert "final identity" in error.message


def test_yaml_site_update_supersedes_reused_state(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sites:
  - site_code: SITE_A
    name: Existing site

updates:
  sites:
    - update:
        site_code: SITE_A
      set:
        site_code: SITE_B
""",
        encoding="utf-8",
    )

    def fake_find_site(site_code):
        assert site_code == "SITE_A"

        return MetadataRow(
            database_id=11,
            values={
                "site_code": "SITE_A",
                "name": "Existing site",
                "description": None,
                "latitude": None,
                "longitude": None,
                "parent_id": None,
            },
        )

    monkeypatch.setattr(
        metadata,
        "find_site",
        fake_find_site,
    )

    config = load_config(config_path)
    plan = resolve_config(config)

    assert plan.errors == ()
    assert plan.raw_items == ()
    assert len(plan.metadata_items) == 2

    items = {
        item.plan_id: item
        for item in plan.metadata_items
    }

    reused = items["sites[0]"]
    updated = items["updates.sites[0]"]

    assert reused.action == PlanAction.REUSE
    assert reused.database_id == 11
    assert reused.values.site_code == "SITE_A"

    assert updated.action == PlanAction.UPDATE
    assert updated.database_id == reused.database_id
    assert updated.values.site_code == "SITE_B"
    assert updated.values.name == "Existing site"

    assert updated.changes == (
        FieldChange(
            field="site_code",
            before="SITE_A",
            after="SITE_B",
            identity_change=True,
        ),
    )
    assert updated.requires_confirmation is True


def test_yaml_site_update_releases_identity_for_another_update(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sites:
  - site_code: SITE_A
    name: First site

updates:
  sites:
    - update:
        site_code: SITE_A
      set:
        site_code: SITE_B

    - update:
        site_code: SITE_C
      set:
        site_code: SITE_A
""",
        encoding="utf-8",
    )

    def fake_find_site(site_code):
        rows = {
            "SITE_A": MetadataRow(
                database_id=11,
                values={
                    "site_code": "SITE_A",
                    "name": "First site",
                    "description": None,
                    "latitude": None,
                    "longitude": None,
                    "parent_id": None,
                },
            ),
            "SITE_C": MetadataRow(
                database_id=12,
                values={
                    "site_code": "SITE_C",
                    "name": "Second site",
                    "description": None,
                    "latitude": None,
                    "longitude": None,
                    "parent_id": None,
                },
            ),
        }
        return rows[site_code]

    monkeypatch.setattr(
        metadata,
        "find_site",
        fake_find_site,
    )

    config = load_config(config_path)
    plan = resolve_config(config)

    assert plan.errors == ()
    assert plan.raw_items == ()
    assert len(plan.metadata_items) == 3

    items = {
        item.plan_id: item
        for item in plan.metadata_items
    }

    reused = items["sites[0]"]
    first_update = items["updates.sites[0]"]
    second_update = items["updates.sites[1]"]

    assert reused.action == PlanAction.REUSE
    assert reused.database_id == 11
    assert reused.values.site_code == "SITE_A"

    assert first_update.action == PlanAction.UPDATE
    assert first_update.database_id == 11
    assert first_update.values.site_code == "SITE_B"
    assert first_update.changes == (
        FieldChange(
            field="site_code",
            before="SITE_A",
            after="SITE_B",
            identity_change=True,
        ),
    )

    assert second_update.action == PlanAction.UPDATE
    assert second_update.database_id == 12
    assert second_update.values.site_code == "SITE_A"
    assert second_update.changes == (
        FieldChange(
            field="site_code",
            before="SITE_C",
            after="SITE_A",
            identity_change=True,
        ),
    )

    assert first_update.requires_confirmation is True
    assert second_update.requires_confirmation is True


def test_yaml_duplicate_site_update_targets_conflict(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
updates:
  sites:
    - update:
        site_code: SITE_A
      set:
        name: New name

    - update:
        site_code: SITE_A
      set:
        description: New description
""",
        encoding="utf-8",
    )

    def fake_find_site(site_code):
        assert site_code == "SITE_A"

        return MetadataRow(
            database_id=11,
            values={
                "site_code": "SITE_A",
                "name": "Old name",
                "description": "Old description",
                "latitude": None,
                "longitude": None,
                "parent_id": None,
            },
        )

    monkeypatch.setattr(
        metadata,
        "find_site",
        fake_find_site,
    )

    config = load_config(config_path)
    plan = resolve_config(config)

    assert plan.raw_items == ()
    assert len(plan.metadata_items) == 2

    items = {
        item.plan_id: item
        for item in plan.metadata_items
    }

    first_update = items["updates.sites[0]"]
    second_update = items["updates.sites[1]"]

    assert first_update.action == PlanAction.UPDATE
    assert second_update.action == PlanAction.UPDATE
    assert first_update.database_id == 11
    assert second_update.database_id == 11

    assert first_update.changes == (
        FieldChange(
            field="name",
            before="Old name",
            after="New name",
            identity_change=False,
        ),
    )
    assert second_update.changes == (
        FieldChange(
            field="description",
            before="Old description",
            after="New description",
            identity_change=False,
        ),
    )

    assert len(plan.errors) == 1

    error = plan.errors[0]

    assert error.code == PlanErrorCode.CONFLICT
    assert error.resource_type == "site"
    assert error.source_path == "updates.sites[1]"
    assert "more than one update" in error.message


def test_yaml_sensor_update_references_new_sensor_model(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
references:
  sensor_types:
    dendrometer:
      type: dendrometer

sensor_models:
  - ref: corrected_model
    manufacturer: Example Instruments
    model: D2
    sensor_type: dendrometer

updates:
  sensors:
    - update:
        serial_number: SENSOR123
      set:
        sensor_model: corrected_model
""",
        encoding="utf-8",
    )

    def fake_find_sensor_type(type_):
        assert type_ == "dendrometer"

        return MetadataRow(
            database_id=2,
            values={
                "type": "dendrometer",
                "description": None,
            },
        )

    def fake_find_sensor_models(**kwargs):
        assert kwargs == {
            "manufacturer": "Example Instruments",
            "model": "D2",
        }
        return ()

    def fake_find_sensors(**kwargs):
        assert kwargs["serial_number"] == "SENSOR123"

        return (
            MetadataRow(
                database_id=17,
                values={
                    "sensor_model_id": 3,
                    "serial_number": "SENSOR123",
                    "description": "Existing sensor",
                },
            ),
        )

    monkeypatch.setattr(
        metadata,
        "find_sensor_type",
        fake_find_sensor_type,
    )
    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        fake_find_sensor_models,
    )
    monkeypatch.setattr(
        metadata,
        "find_sensors",
        fake_find_sensors,
    )

    config = load_config(config_path)
    plan = resolve_config(config)

    assert plan.errors == ()
    assert plan.raw_items == ()
    assert len(plan.metadata_items) == 2

    items = {
        item.plan_id: item
        for item in plan.metadata_items
    }

    model = items["sensor_models[0]"]
    sensor = items["updates.sensors[0]"]

    assert model.resource_type == "sensor_model"
    assert model.action == PlanAction.CREATE
    assert model.database_id is None
    assert model.values.manufacturer == "Example Instruments"
    assert model.values.model == "D2"
    assert model.values.sensor_type == ExistingRef(
        resource_type="sensor_type",
        database_id=2,
    )

    model_reference = PlannedRef(
        resource_type="sensor_model",
        plan_id=model.plan_id,
    )

    assert sensor.resource_type == "sensor"
    assert sensor.action == PlanAction.UPDATE
    assert sensor.database_id == 17
    assert sensor.values.sensor_model == model_reference
    assert sensor.values.serial_number == "SENSOR123"
    assert sensor.values.description == "Existing sensor"

    assert sensor.changes == (
        FieldChange(
            field="sensor_model",
            before=ExistingRef(
                resource_type="sensor_model",
                database_id=3,
            ),
            after=model_reference,
            identity_change=True,
        ),
    )
    assert sensor.requires_confirmation is True


def test_yaml_location_update_references_new_site(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sites:
  - ref: corrected_site
    site_code: SITE_B
    name: Corrected site

updates:
  locations:
    - update:
        initial_label: tree_001
      set:
        site: corrected_site
""",
        encoding="utf-8",
    )

    def fake_find_site(site_code):
        assert site_code == "SITE_B"

    def fake_find_locations(**kwargs):
        assert kwargs["initial_label"] == "tree_001"

        return (
            MetadataRow(
                database_id=71,
                values={
                    "site_id": 11,
                    "location_type_id": 21,
                    "latitude": 54.10,
                    "longitude": 13.40,
                    "height_above_ground": 1.30,
                    "azimuth": 180.0,
                    "initial_label": "tree_001",
                    "initial_label_valid_from": None,
                    "initial_label_valid_to": None,
                },
            ),
        )

    monkeypatch.setattr(
        metadata,
        "find_site",
        fake_find_site,
    )
    monkeypatch.setattr(
        metadata,
        "find_locations",
        fake_find_locations,
    )

    config = load_config(config_path)
    plan = resolve_config(config)

    assert plan.errors == ()
    assert plan.raw_items == ()
    assert len(plan.metadata_items) == 2

    items = {
        item.plan_id: item
        for item in plan.metadata_items
    }

    site = items["sites[0]"]
    location = items["updates.locations[0]"]

    assert site.resource_type == "site"
    assert site.action == PlanAction.CREATE
    assert site.database_id is None
    assert site.values.site_code == "SITE_B"
    assert site.values.name == "Corrected site"

    site_reference = PlannedRef(
        resource_type="site",
        plan_id=site.plan_id,
    )

    assert location.resource_type == "location"
    assert location.action == PlanAction.UPDATE
    assert location.database_id == 71

    assert location.values.site == site_reference
    assert location.values.location_type == ExistingRef(
        resource_type="location_type",
        database_id=21,
    )
    assert location.values.latitude == 54.10
    assert location.values.longitude == 13.40
    assert location.values.height_above_ground == 1.30
    assert location.values.azimuth == 180.0

    assert location.identity is not None
    assert dict(location.identity.components) == {
        "site": site_reference,
        "initial_label": "tree_001",
    }

    assert location.changes == (
        FieldChange(
            field="site",
            before=ExistingRef(
                resource_type="site",
                database_id=11,
            ),
            after=site_reference,
            identity_change=True,
        ),
    )
    assert location.requires_confirmation is True


def test_yaml_location_updates_conflict_at_new_site(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
references:
  sites:
    source_a:
      site_code: SITE_A
    source_c:
      site_code: SITE_C

sites:
  - ref: destination
    site_code: SITE_B
    name: Destination site

updates:
  locations:
    - update:
        site: source_a
        initial_label: tree_001
      set:
        site: destination

    - update:
        site: source_c
        initial_label: tree_001
      set:
        site: destination
""",
        encoding="utf-8",
    )

    def fake_find_site(site_code):
        if site_code == "SITE_B":
            return None

        database_id = {
            "SITE_A": 11,
            "SITE_C": 12,
        }[site_code]

        return MetadataRow(
            database_id=database_id,
            values={
                "site_code": site_code,
                "name": site_code,
                "description": None,
                "latitude": None,
                "longitude": None,
                "parent_id": None,
            },
        )

    def fake_find_locations(**kwargs):
        assert kwargs["initial_label"] == "tree_001"

        site_id = kwargs["site_id"]
        location_id = {
            11: 71,
            12: 72,
        }[site_id]

        return (
            MetadataRow(
                database_id=location_id,
                values={
                    "site_id": site_id,
                    "location_type_id": 21,
                    "latitude": None,
                    "longitude": None,
                    "height_above_ground": None,
                    "azimuth": None,
                    "initial_label": "tree_001",
                    "initial_label_valid_from": None,
                    "initial_label_valid_to": None,
                },
            ),
        )

    monkeypatch.setattr(
        metadata,
        "find_site",
        fake_find_site,
    )
    monkeypatch.setattr(
        metadata,
        "find_locations",
        fake_find_locations,
    )

    plan = resolve_config(load_config(config_path))

    assert plan.raw_items == ()
    assert len(plan.metadata_items) == 3

    items = {
        item.plan_id: item
        for item in plan.metadata_items
    }

    site = items["sites[0]"]
    first = items["updates.locations[0]"]
    second = items["updates.locations[1]"]

    assert site.action == PlanAction.CREATE
    assert site.database_id is None

    site_reference = PlannedRef(
        resource_type="site",
        plan_id=site.plan_id,
    )

    for item, database_id in ((first, 71), (second, 72)):
        assert item.action == PlanAction.UPDATE
        assert item.database_id == database_id
        assert item.values.site == site_reference
        assert item.identity is not None
        assert dict(item.identity.components) == {
            "site": site_reference,
            "initial_label": "tree_001",
        }
        assert item.requires_confirmation is True

    assert len(plan.errors) == 1

    error = plan.errors[0]

    assert error.code == PlanErrorCode.CONFLICT
    assert error.resource_type == "location"
    assert error.source_path == "updates.locations[1]"
    assert "final identity" in error.message


def test_yaml_sensor_model_identity_correction(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
updates:
  sensor_models:
    - update:
        manufacturer: Old manufacturer
        model: Old model
      set:
        manufacturer: Correct manufacturer
        model: Correct model
""",
        encoding="utf-8",
    )

    def fake_find_sensor_models(**kwargs):
        assert kwargs == {
            "manufacturer": "Old manufacturer",
            "model": "Old model",
        }

        return (
            MetadataRow(
                database_id=31,
                values={
                    "manufacturer": "Old manufacturer",
                    "model": "Old model",
                    "sensor_type_id": 2,
                },
            ),
        )

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        fake_find_sensor_models,
    )

    plan = resolve_config(load_config(config_path))

    assert plan.errors == ()
    assert plan.raw_items == ()
    assert len(plan.metadata_items) == 1

    item = plan.metadata_items[0]

    assert item.plan_id == "updates.sensor_models[0]"
    assert item.resource_type == "sensor_model"
    assert item.action == PlanAction.UPDATE
    assert item.database_id == 31

    assert item.values.manufacturer == "Correct manufacturer"
    assert item.values.model == "Correct model"
    assert item.values.sensor_type == ExistingRef(
        resource_type="sensor_type",
        database_id=2,
    )

    assert item.changes == (
        FieldChange(
            field="manufacturer",
            before="Old manufacturer",
            after="Correct manufacturer",
            identity_change=True,
        ),
        FieldChange(
            field="model",
            before="Old model",
            after="Correct model",
            identity_change=True,
        ),
    )
    assert item.requires_confirmation is True


def test_yaml_combines_simple_resource_updates(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
updates:
  location_types:
    - update:
        type: stem
      set:
        description: New location description

  sensor_types:
    - update:
        type: dendrometer
      set:
        description: New sensor description

  variables:
    - update:
        variable: stem_radius
      set:
        description: New variable description
""",
        encoding="utf-8",
    )

    def fake_find_location_type(type_):
        assert type_ == "stem"

        return MetadataRow(
            database_id=21,
            values={
                "type": "stem",
                "description": "Old location description",
            },
        )

    def fake_find_sensor_type(type_):
        assert type_ == "dendrometer"

        return MetadataRow(
            database_id=22,
            values={
                "type": "dendrometer",
                "description": "Old sensor description",
            },
        )

    def fake_find_variable(variable):
        assert variable == "stem_radius"

        return MetadataRow(
            database_id=23,
            values={
                "variable": "stem_radius",
                "derived": False,
                "description": "Old variable description",
            },
        )

    monkeypatch.setattr(
        metadata,
        "find_location_type",
        fake_find_location_type,
    )
    monkeypatch.setattr(
        metadata,
        "find_sensor_type",
        fake_find_sensor_type,
    )
    monkeypatch.setattr(
        metadata,
        "find_variable",
        fake_find_variable,
    )

    plan = resolve_config(load_config(config_path))

    assert plan.errors == ()
    assert plan.raw_items == ()
    assert len(plan.metadata_items) == 3

    items = {
        item.plan_id: item
        for item in plan.metadata_items
    }

    expected = (
        (
            "updates.location_types[0]",
            "location_type",
            21,
            "Old location description",
            "New location description",
        ),
        (
            "updates.sensor_types[0]",
            "sensor_type",
            22,
            "Old sensor description",
            "New sensor description",
        ),
        (
            "updates.variables[0]",
            "variable",
            23,
            "Old variable description",
            "New variable description",
        ),
    )

    for plan_id, resource_type, database_id, before, after in expected:
        item = items[plan_id]

        assert item.resource_type == resource_type
        assert item.action == PlanAction.UPDATE
        assert item.database_id == database_id
        assert item.values.description == after
        assert item.changes == (
            FieldChange(
                field="description",
                before=before,
                after=after,
                identity_change=False,
            ),
        )
        assert item.requires_confirmation is False

    assert items["updates.location_types[0]"].values.type == "stem"
    assert items["updates.sensor_types[0]"].values.type == "dendrometer"
    assert items["updates.variables[0]"].values.variable == "stem_radius"
    assert items["updates.variables[0]"].values.derived is False


def test_yaml_unchanged_updates_produce_empty_plan(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
updates:
  sites:
    - update:
        site_code: SITE_A
      set:
        site_code: SITE_A
        name: Existing site

  sensor_models:
    - update:
        manufacturer: Example Instruments
        model: D2
      set:
        manufacturer: Example Instruments
        model: D2
""",
        encoding="utf-8",
    )

    calls = {
        "site": 0,
        "sensor_model": 0,
    }

    def fake_find_site(site_code):
        assert site_code == "SITE_A"
        calls["site"] += 1

        return MetadataRow(
            database_id=11,
            values={
                "site_code": "SITE_A",
                "name": "Existing site",
                "description": None,
                "latitude": None,
                "longitude": None,
                "parent_id": None,
            },
        )

    def fake_find_sensor_models(**kwargs):
        assert kwargs == {
            "manufacturer": "Example Instruments",
            "model": "D2",
        }
        calls["sensor_model"] += 1

        return (
            MetadataRow(
                database_id=31,
                values={
                    "manufacturer": "Example Instruments",
                    "model": "D2",
                    "sensor_type_id": 2,
                },
            ),
        )

    monkeypatch.setattr(
        metadata,
        "find_site",
        fake_find_site,
    )
    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        fake_find_sensor_models,
    )

    plan = resolve_config(load_config(config_path))

    assert calls == {
        "site": 1,
        "sensor_model": 1,
    }
    assert plan.metadata_items == ()
    assert plan.raw_items == ()
    assert plan.errors == ()
    assert plan.warnings == ()

