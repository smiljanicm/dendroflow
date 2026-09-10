from datetime import datetime, timezone

from dendroflow.configuration import ConfigModel, metadata, validate_config
from dendroflow.configuration.metadata import MetadataRow
from dendroflow.configuration.plan import (
    ExistingRef,
    PlanAction,
    PlanBinding,
    PlanErrorCode,
    PlannedRef,
    ResolvedLocationValues,
    ResolvedPlanItem,
)
from dendroflow.configuration.resolver import (
    DeclarationAlias,
    ReferenceAlias,
    build_alias_registry,
    resolve_deployment_declarations,
    resolve_deployment_reference_aliases,
    resolve_location_declarations,
    resolve_location_label_declarations,
    resolve_location_reference_aliases,
    resolve_metadata_config,
    resolve_sensor_declarations,
    resolve_sensor_model_declarations,
    resolve_sensor_model_reference_aliases,
    resolve_sensor_reference_aliases,
    resolve_simple_declarations,
    resolve_simple_reference_aliases,
)


def test_registry_contains_declaration_alias():
    config = ConfigModel(
        variables=[
            {
                "ref": "water_level",
                "variable": "water_level",
            }
        ]
    )

    validate_config(config)
    registry = build_alias_registry(config)

    entry = registry.get("variables", "water_level")

    assert isinstance(entry, DeclarationAlias)
    assert entry.declaration_index == 0
    assert entry.source_path == "variables[0].ref"


def test_registry_contains_reference_alias():
    config = ConfigModel(
        references={
            "sensor_models": {
                "cs451": {
                    "manufacturer": "Campbell Scientific",
                    "model": "CS451",
                }
            }
        }
    )

    validate_config(config)
    registry = build_alias_registry(config)

    entry = registry.get("sensor_models", "cs451")

    assert isinstance(entry, ReferenceAlias)
    assert entry.selector.model == "CS451"


def test_registry_ignores_declaration_without_ref():
    config = ConfigModel(
        variables=[
            {
                "variable": "water_level",
            }
        ]
    )

    validate_config(config)
    registry = build_alias_registry(config)

    assert registry.aliases("variables") == ()


def test_registry_scopes_aliases_by_resource_type():
    config = ConfigModel(
        variables=[
            {
                "ref": "main",
                "variable": "water_level",
            }
        ],
        references={
            "sensors": {
                "main": {
                    "serial_number": "123456",
                }
            }
        },
    )

    validate_config(config)
    registry = build_alias_registry(config)

    variable = registry.get("variables", "main")
    sensor = registry.get("sensors", "main")

    assert isinstance(variable, DeclarationAlias)
    assert isinstance(sensor, ReferenceAlias)


def test_registry_returns_none_for_unknown_alias():
    config = ConfigModel()

    validate_config(config)
    registry = build_alias_registry(config)

    assert registry.get("variables", "missing") is None


def test_reference_selector_is_not_resolved_as_local_alias():
    config = ConfigModel(
        references={
            "deployments": {
                "water_level_main": {
                    "sensor": "123456",
                }
            }
        }
    )

    validate_config(config)
    registry = build_alias_registry(config)

    entry = registry.get(
        "deployments",
        "water_level_main",
    )

    assert isinstance(entry, ReferenceAlias)
    assert entry.selector.sensor == "123456"
    assert registry.get("sensors", "123456") is None


def test_resolve_simple_reference_alias_existing_variable(
    monkeypatch,
):
    config = ConfigModel(
        references={
            "variables": {
                "water_level": {
                    "variable": "water_level",
                }
            }
        }
    )
    registry = build_alias_registry(config)

    monkeypatch.setattr(
        metadata,
        "find_variable",
        lambda variable: MetadataRow(
            database_id=7,
            values={
                "variable": variable,
                "derived": False,
                "description": "Water level",
            },
        ),
    )

    bindings, errors = resolve_simple_reference_aliases(
        registry
    )

    assert errors == ()
    assert len(bindings) == 1

    binding = bindings[0]
    assert binding.resource_type == "variables"
    assert binding.alias == "water_level"
    assert binding.resource == ExistingRef(
        resource_type="variable",
        database_id=7,
    )


def test_resolve_simple_reference_alias_reports_not_found(
    monkeypatch,
):
    config = ConfigModel(
        references={
            "variables": {
                "water_level": {
                    "variable": "water_level",
                }
            }
        }
    )
    registry = build_alias_registry(config)

    monkeypatch.setattr(
        metadata,
        "find_variable",
        lambda variable: None,
    )

    bindings, errors = resolve_simple_reference_aliases(
        registry
    )

    assert bindings == ()
    assert len(errors) == 1

    error = errors[0]
    assert error.code == PlanErrorCode.NOT_FOUND
    assert error.source_path == (
        "references.variables.water_level"
    )


def test_resolve_location_type_reference_uses_type(
    monkeypatch,
):
    config = ConfigModel(
        references={
            "location_types": {
                "well": {
                    "type": "well",
                }
            }
        }
    )
    registry = build_alias_registry(config)

    received = []

    def fake_find_location_type(type_):
        received.append(type_)
        return MetadataRow(
            database_id=3,
            values={
                "type": type_,
                "description": None,
            },
        )

    monkeypatch.setattr(
        metadata,
        "find_location_type",
        fake_find_location_type,
    )

    bindings, errors = resolve_simple_reference_aliases(
        registry
    )

    assert errors == ()
    assert received == ["well"]
    assert bindings[0].resource.database_id == 3


def test_simple_reference_resolution_ignores_declarations(
    monkeypatch,
):
    config = ConfigModel(
        variables=[
            {
                "ref": "water_level",
                "variable": "water_level",
            }
        ]
    )
    registry = build_alias_registry(config)

    called = False

    def fake_find_variable(variable):
        nonlocal called
        called = True

    monkeypatch.setattr(
        metadata,
        "find_variable",
        fake_find_variable,
    )

    bindings, errors = resolve_simple_reference_aliases(
        registry
    )

    assert bindings == ()
    assert errors == ()
    assert not called


def test_new_variable_becomes_create_and_planned_ref(monkeypatch):
    config = ConfigModel(
        variables=[
            {
                "ref": "water_level",
                "variable": "water_level",
                "description": "Water level",
            }
        ]
    )

    monkeypatch.setattr(
        metadata,
        "find_variable",
        lambda variable: None,
    )

    items, bindings, errors = resolve_simple_declarations(config)

    assert errors == ()
    assert len(items) == 1
    assert items[0].action == PlanAction.CREATE
    assert items[0].database_id is None
    assert items[0].values.variable == "water_level"

    assert bindings[0].resource == PlannedRef(
        resource_type="variable",
        plan_id="variables[0]",
    )


def test_existing_variable_becomes_reuse_and_existing_ref(monkeypatch):
    config = ConfigModel(
        variables=[
            {
                "ref": "water_level",
                "variable": "water_level",
                "description": "Water level",
            }
        ]
    )

    monkeypatch.setattr(
        metadata,
        "find_variable",
        lambda variable: MetadataRow(
            database_id=7,
            values={
                "variable": variable,
                "derived": False,
                "description": "Water level",
            },
        ),
    )

    items, bindings, errors = resolve_simple_declarations(config)

    assert errors == ()
    assert items[0].action == PlanAction.REUSE
    assert items[0].database_id == 7

    assert bindings[0].resource == ExistingRef(
        resource_type="variable",
        database_id=7,
    )


def test_existing_variable_explicit_description_conflict(monkeypatch):
    config = ConfigModel(
        variables=[
            {
                "variable": "water_level",
                "description": "Requested description",
            }
        ]
    )

    monkeypatch.setattr(
        metadata,
        "find_variable",
        lambda variable: MetadataRow(
            database_id=1,
            values={
                "variable": variable,
                "derived": False,
                "description": "Existing description",
            },
        ),
    )

    _, _, errors = resolve_simple_declarations(config)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].source_path == "variables[0].description"


def test_existing_variable_ignores_omitted_description(monkeypatch):
    config = ConfigModel(
        variables=[
            {
                "variable": "water_level",
            }
        ]
    )

    monkeypatch.setattr(
        metadata,
        "find_variable",
        lambda variable: MetadataRow(
            database_id=1,
            values={
                "variable": variable,
                "derived": False,
                "description": "Existing description",
            },
        ),
    )

    items, _, errors = resolve_simple_declarations(config)

    assert errors == ()
    assert items[0].action == PlanAction.REUSE
    assert items[0].values.description == "Existing description"


def test_existing_variable_derived_difference_is_conflict(monkeypatch):
    config = ConfigModel(
        variables=[
            {
                "variable": "water_level",
                "derived": True,
            }
        ]
    )

    monkeypatch.setattr(
        metadata,
        "find_variable",
        lambda variable: MetadataRow(
            database_id=1,
            values={
                "variable": variable,
                "derived": False,
                "description": None,
            },
        ),
    )

    _, _, errors = resolve_simple_declarations(config)

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].source_path == "variables[0].derived"


def test_declaration_without_ref_still_creates_plan_item(monkeypatch):
    config = ConfigModel(
        location_types=[
            {
                "type": "well",
            }
        ]
    )

    monkeypatch.setattr(
        metadata,
        "find_location_type",
        lambda type_: None,
    )

    items, bindings, errors = resolve_simple_declarations(config)

    assert errors == ()
    assert len(items) == 1
    assert items[0].action == PlanAction.CREATE
    assert bindings == ()


def test_new_child_site_can_reference_new_parent(monkeypatch):
    config = ConfigModel(
        sites=[
            {
                "ref": "parent",
                "site_code": "parent_site",
                "name": "Parent",
            },
            {
                "ref": "child",
                "site_code": "child_site",
                "name": "Child",
                "parent": "parent",
            },
        ]
    )

    monkeypatch.setattr(
        metadata,
        "find_site",
        lambda site_code: None,
    )

    items, bindings, errors = resolve_simple_declarations(config)

    assert errors == ()

    child = items[1]

    assert child.values.parent == PlannedRef(
        resource_type="site",
        plan_id="sites[0]",
    )

    assert len(bindings) == 2


def test_existing_child_site_resolves_existing_parent(monkeypatch):
    config = ConfigModel(
        references={
            "sites": {
                "parent": {
                    "site_code": "parent_site",
                }
            }
        },
        sites=[
            {
                "site_code": "child_site",
                "name": "Child",
                "parent": "parent",
            }
        ],
    )

    registry = build_alias_registry(config)

    monkeypatch.setattr(
        metadata,
        "find_site",
        lambda site_code: (
            MetadataRow(
                database_id=10,
                values={
                    "site_code": "parent_site",
                    "name": "Parent",
                    "description": None,
                    "latitude": None,
                    "longitude": None,
                    "parent_id": None,
                },
            )
            if site_code == "parent_site"
            else MetadataRow(
                database_id=20,
                values={
                    "site_code": "child_site",
                    "name": "Child",
                    "description": None,
                    "latitude": None,
                    "longitude": None,
                    "parent_id": 10,
                },
            )
        ),
    )

    reference_bindings, reference_errors = (
        resolve_simple_reference_aliases(registry)
    )

    assert reference_errors == ()

    items, _, errors = resolve_simple_declarations(
        config,
        existing_bindings=reference_bindings,
    )

    assert errors == ()
    assert items[0].values.parent == ExistingRef(
        resource_type="site",
        database_id=10,
    )


# Metadata tests


def test_sensor_model_reference_resolves_unique_match(
    monkeypatch,
):
    config = ConfigModel(
        references={
            "sensor_models": {
                "cs451": {
                    "model": "CS451",
                }
            }
        }
    )

    registry = build_alias_registry(config)

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (
            MetadataRow(
                database_id=3,
                values={
                    "model": "CS451",
                    "manufacturer": "Campbell Scientific",
                    "sensor_type_id": 1,
                },
            ),
        ),
    )

    bindings, errors = (
        resolve_sensor_model_reference_aliases(registry)
    )

    assert errors == ()
    assert bindings[0].resource == ExistingRef(
        resource_type="sensor_model",
        database_id=3,
    )


def test_sensor_model_reference_reports_ambiguity(
    monkeypatch,
):
    config = ConfigModel(
        references={
            "sensor_models": {
                "cs451": {
                    "model": "CS451",
                }
            }
        }
    )

    registry = build_alias_registry(config)

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (
            MetadataRow(3, {}),
            MetadataRow(8, {}),
        ),
    )

    bindings, errors = (
        resolve_sensor_model_reference_aliases(registry)
    )

    assert bindings == ()
    assert errors[0].code == PlanErrorCode.AMBIGUOUS
    assert errors[0].candidate_ids == (3, 8)


def test_sensor_model_reference_reports_not_found(
    monkeypatch,
):
    config = ConfigModel(
        references={
            "sensor_models": {
                "cs451": {
                    "manufacturer": "Campbell Scientific",
                    "model": "CS451",
                }
            }
        }
    )

    registry = build_alias_registry(config)

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (),
    )

    bindings, errors = (
        resolve_sensor_model_reference_aliases(registry)
    )

    assert bindings == ()
    assert errors[0].code == PlanErrorCode.NOT_FOUND


def test_new_sensor_model_becomes_create(
    monkeypatch,
):
    config = ConfigModel(
        sensor_models=[
            {
                "ref": "cs451",
                "manufacturer": "Campbell Scientific",
                "model": "CS451",
                "sensor_type": "water_level",
            }
        ]
    )

    sensor_type_bindings = (
        PlanBinding(
            resource_type="sensor_types",
            alias="water_level",
            resource=ExistingRef(
                resource_type="sensor_type",
                database_id=1,
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (),
    )

    items, bindings, errors = (
        resolve_sensor_model_declarations(
            config,
            existing_bindings=sensor_type_bindings,
        )
    )

    assert errors == ()
    assert items[0].action == PlanAction.CREATE
    assert items[0].values.sensor_type == ExistingRef(
        resource_type="sensor_type",
        database_id=1,
    )
    assert bindings[0].resource == PlannedRef(
        resource_type="sensor_model",
        plan_id="sensor_models[0]",
    )


def test_new_sensor_model_can_use_planned_sensor_type(
    monkeypatch,
):
    config = ConfigModel(
        sensor_models=[
            {
                "manufacturer": "TEST",
                "model": "MODEL",
                "sensor_type": "new_type",
            }
        ]
    )

    sensor_type_bindings = (
        PlanBinding(
            resource_type="sensor_types",
            alias="new_type",
            resource=PlannedRef(
                resource_type="sensor_type",
                plan_id="sensor_types[0]",
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (),
    )

    items, _, errors = resolve_sensor_model_declarations(
        config,
        existing_bindings=sensor_type_bindings,
    )

    assert errors == ()
    assert items[0].values.sensor_type == PlannedRef(
        resource_type="sensor_type",
        plan_id="sensor_types[0]",
    )


def test_existing_sensor_model_becomes_reuse(
    monkeypatch,
):
    config = ConfigModel(
        sensor_models=[
            {
                "ref": "cs451",
                "manufacturer": "Campbell Scientific",
                "model": "CS451",
                "sensor_type": "water_level",
            }
        ]
    )

    sensor_type_bindings = (
        PlanBinding(
            resource_type="sensor_types",
            alias="water_level",
            resource=ExistingRef(
                resource_type="sensor_type",
                database_id=1,
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (
            MetadataRow(
                database_id=3,
                values={
                    "model": "CS451",
                    "manufacturer": "Campbell Scientific",
                    "sensor_type_id": 1,
                },
            ),
        ),
    )

    items, bindings, errors = (
        resolve_sensor_model_declarations(
            config,
            existing_bindings=sensor_type_bindings,
        )
    )

    assert errors == ()
    assert items[0].action == PlanAction.REUSE
    assert items[0].database_id == 3
    assert bindings[0].resource == ExistingRef(
        resource_type="sensor_model",
        database_id=3,
    )


def test_existing_sensor_model_reports_sensor_type_conflict(
    monkeypatch,
):
    config = ConfigModel(
        sensor_models=[
            {
                "manufacturer": "Campbell Scientific",
                "model": "CS451",
                "sensor_type": "requested_type",
            }
        ]
    )

    sensor_type_bindings = (
        PlanBinding(
            resource_type="sensor_types",
            alias="requested_type",
            resource=ExistingRef(
                resource_type="sensor_type",
                database_id=2,
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (
            MetadataRow(
                database_id=3,
                values={
                    "model": "CS451",
                    "manufacturer": "Campbell Scientific",
                    "sensor_type_id": 1,
                },
            ),
        ),
    )

    items, _, errors = resolve_sensor_model_declarations(
        config,
        existing_bindings=sensor_type_bindings,
    )

    assert items[0].action == PlanAction.REUSE
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT


def test_new_sensor_with_planned_model_does_not_query_database(
    monkeypatch,
):
    config = ConfigModel(
        sensors=[
            {
                "ref": "sensor_01",
                "serial_number": "123456",
                "sensor_model": "new_model",
            }
        ]
    )

    model_bindings = (
        PlanBinding(
            resource_type="sensor_models",
            alias="new_model",
            resource=PlannedRef(
                resource_type="sensor_model",
                plan_id="sensor_models[0]",
            ),
        ),
    )

    called = False

    def fake_find_sensors(**kwargs):
        nonlocal called
        called = True
        return ()

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        fake_find_sensors,
    )

    items, bindings, errors = resolve_sensor_declarations(
        config,
        existing_bindings=model_bindings,
    )

    assert errors == ()
    assert not called
    assert items[0].action == PlanAction.CREATE
    assert items[0].values.sensor_model == PlannedRef(
        resource_type="sensor_model",
        plan_id="sensor_models[0]",
    )
    assert bindings[0].resource == PlannedRef(
        resource_type="sensor",
        plan_id="sensors[0]",
    )


def test_sensor_reference_reports_ambiguity(monkeypatch):
    config = ConfigModel(
        references={
            "sensors": {
                "sensor_01": {
                    "serial_number": "123456",
                }
            }
        }
    )

    registry = build_alias_registry(config)

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (
            MetadataRow(7, {}),
            MetadataRow(8, {}),
        ),
    )

    bindings, errors = resolve_sensor_reference_aliases(
        registry
    )

    assert bindings == ()
    assert errors[0].code == PlanErrorCode.AMBIGUOUS
    assert errors[0].candidate_ids == (7, 8)


def test_existing_sensor_becomes_reuse(monkeypatch):
    config = ConfigModel(
        sensors=[
            {
                "ref": "sensor_01",
                "serial_number": "123456",
                "sensor_model": "cs451",
            }
        ]
    )

    model_bindings = (
        PlanBinding(
            resource_type="sensor_models",
            alias="cs451",
            resource=ExistingRef(
                resource_type="sensor_model",
                database_id=3,
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (
            MetadataRow(
                database_id=7,
                values={
                    "sensor_model_id": 3,
                    "serial_number": "123456",
                    "description": "Existing sensor",
                },
            ),
        ),
    )

    items, bindings, errors = resolve_sensor_declarations(
        config,
        existing_bindings=model_bindings,
    )

    assert errors == ()
    assert items[0].action == PlanAction.REUSE
    assert items[0].database_id == 7
    assert items[0].values.description == "Existing sensor"
    assert bindings[0].resource == ExistingRef(
        resource_type="sensor",
        database_id=7,
    )


def test_new_location_with_planned_site_does_not_query_database(
    monkeypatch,
):
    config = ConfigModel(
        locations=[
            {
                "ref": "well_01",
                "site": "new_site",
                "location_type": "well",
                "initial_label": {
                    "label": "Well 01",
                    "valid_from": "2025-01-01T00:00:00Z",
                },
            }
        ]
    )

    existing_bindings = (
        PlanBinding(
            resource_type="sites",
            alias="new_site",
            resource=PlannedRef(
                resource_type="site",
                plan_id="sites[0]",
            ),
        ),
        PlanBinding(
            resource_type="location_types",
            alias="well",
            resource=ExistingRef(
                resource_type="location_type",
                database_id=2,
            ),
        ),
    )

    called = False

    def fake_find_locations(**kwargs):
        nonlocal called
        called = True
        return ()

    monkeypatch.setattr(
        metadata,
        "find_locations",
        fake_find_locations,
    )

    items, bindings, errors = resolve_location_declarations(
        config,
        existing_bindings=existing_bindings,
    )

    assert errors == ()
    assert not called
    assert items[0].action == PlanAction.CREATE
    assert bindings[0].resource == PlannedRef(
        resource_type="location",
        plan_id="locations[0]",
    )


def test_existing_location_becomes_reuse(monkeypatch):
    config = ConfigModel(
        locations=[
            {
                "ref": "well_01",
                "site": "sandhagen",
                "location_type": "well",
                "initial_label": {
                    "label": "Well 01",
                    "valid_from": "2025-01-01T00:00:00Z",
                },
            }
        ]
    )

    existing_bindings = (
        PlanBinding(
            resource_type="sites",
            alias="sandhagen",
            resource=ExistingRef(
                resource_type="site",
                database_id=1,
            ),
        ),
        PlanBinding(
            resource_type="location_types",
            alias="well",
            resource=ExistingRef(
                resource_type="location_type",
                database_id=2,
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (
            MetadataRow(
                database_id=3,
                values={
                    "site_id": 1,
                    "location_type_id": 2,
                    "latitude": None,
                    "longitude": None,
                    "height_above_ground": None,
                    "azimuth": None,
                    "initial_label": "Well 01",
                    "initial_label_valid_from": (
                        "2025-01-01T00:00:00+00:00"
                    ),
                    "initial_label_valid_to": None,
                },
            ),
        ),
    )

    items, bindings, errors = resolve_location_declarations(
        config,
        existing_bindings=existing_bindings,
    )

    assert errors == ()
    assert items[0].action == PlanAction.REUSE
    assert items[0].database_id == 3
    assert bindings[0].resource == ExistingRef(
        resource_type="location",
        database_id=3,
    )


def test_location_reference_reports_ambiguity(monkeypatch):
    config = ConfigModel(
        references={
            "locations": {
                "well_01": {
                    "initial_label": "Well 01",
                }
            }
        }
    )

    registry = build_alias_registry(config)

    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (
            MetadataRow(3, {}),
            MetadataRow(7, {}),
        ),
    )

    bindings, errors = resolve_location_reference_aliases(
        registry
    )

    assert bindings == ()
    assert errors[0].code == PlanErrorCode.AMBIGUOUS
    assert errors[0].candidate_ids == (3, 7)


def test_initial_label_for_new_location_becomes_create():
    config = ConfigModel(
        locations=[
            {
                "site": "sandhagen",
                "location_type": "well",
                "initial_label": {
                    "label": "Well 01",
                    "valid_from": "2025-01-01T00:00:00Z",
                },
            }
        ]
    )

    location_items = (
        ResolvedPlanItem(
            plan_id="locations[0]",
            resource_type="location",
            action=PlanAction.CREATE,
            values=ResolvedLocationValues(
                site=PlannedRef(
                    resource_type="site",
                    plan_id="sites[0]",
                ),
                location_type=ExistingRef(
                    resource_type="location_type",
                    database_id=2,
                ),
                latitude=None,
                longitude=None,
                height_above_ground=None,
                azimuth=None,
            ),
            source_path="locations[0]",
        ),
    )

    items, errors = resolve_location_label_declarations(
        config,
        location_items,
    )

    assert errors == ()
    assert len(items) == 1
    assert items[0].action == PlanAction.CREATE
    assert items[0].plan_id == "locations[0].initial_label"
    assert items[0].values.location == PlannedRef(
        resource_type="location",
        plan_id="locations[0]",
    )


def test_existing_initial_label_becomes_reuse(monkeypatch):
    config = ConfigModel(
        locations=[
            {
                "site": "sandhagen",
                "location_type": "well",
                "initial_label": {
                    "label": "Well 01",
                    "valid_from": "2025-01-01T00:00:00Z",
                },
            }
        ]
    )

    location_items = (
        ResolvedPlanItem(
            plan_id="locations[0]",
            resource_type="location",
            action=PlanAction.REUSE,
            database_id=3,
            values=ResolvedLocationValues(
                site=ExistingRef(
                    resource_type="site",
                    database_id=1,
                ),
                location_type=ExistingRef(
                    resource_type="location_type",
                    database_id=2,
                ),
                latitude=None,
                longitude=None,
                height_above_ground=None,
                azimuth=None,
            ),
            source_path="locations[0]",
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_location_labels",
        lambda location_id: (
            MetadataRow(
                database_id=10,
                values={
                    "location_id": 3,
                    "label": "Well 01",
                    "valid_from": config.locations[
                        0
                    ].initial_label.valid_from,
                    "valid_to": None,
                },
            ),
        ),
    )

    items, errors = resolve_location_label_declarations(
        config,
        location_items,
    )

    assert errors == ()
    assert items[0].action == PlanAction.REUSE
    assert items[0].database_id == 10


def test_top_level_label_for_planned_location_becomes_create():
    config = ConfigModel(
        location_labels=[
            {
                "location": "well_01",
                "label": "Well B",
                "valid_from": "2026-01-01T00:00:00Z",
            }
        ]
    )

    location_ref = PlannedRef(
        resource_type="location",
        plan_id="locations[0]",
    )

    existing_bindings = (
        PlanBinding(
            resource_type="locations",
            alias="well_01",
            resource=location_ref,
        ),
    )

    items, errors = resolve_location_label_declarations(
        config,
        location_items=(),
        existing_bindings=existing_bindings,
    )

    assert errors == ()
    assert len(items) == 1

    item = items[0]

    assert item.plan_id == "location_labels[0]"
    assert item.resource_type == "location_label"
    assert item.action == PlanAction.CREATE
    assert item.values.location == location_ref
    assert item.values.label == "Well B"


def test_top_level_label_requires_location_binding():
    config = ConfigModel(
        location_labels=[
            {
                "location": "missing_location",
                "label": "Well B",
                "valid_from": "2026-01-01T00:00:00Z",
            }
        ]
    )

    items, errors = resolve_location_label_declarations(
        config,
        location_items=(),
    )

    assert items == ()
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.INVALID_REFERENCE
    assert errors[0].resource_type == "location_label"
    assert errors[0].source_path == "location_labels[0].location"


def test_top_level_existing_label_becomes_reuse(monkeypatch):
    valid_from = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )

    config = ConfigModel(
        location_labels=[
            {
                "location": "well_01",
                "label": "Well B",
                "valid_from": valid_from,
            }
        ]
    )

    existing_bindings = (
        PlanBinding(
            resource_type="locations",
            alias="well_01",
            resource=ExistingRef(
                resource_type="location",
                database_id=3,
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_location_labels",
        lambda location_id: (
            MetadataRow(
                database_id=11,
                values={
                    "location_id": 3,
                    "label": "Well B",
                    "valid_from": valid_from,
                    "valid_to": None,
                },
            ),
        ),
    )

    items, errors = resolve_location_label_declarations(
        config,
        location_items=(),
        existing_bindings=existing_bindings,
    )

    assert errors == ()
    assert len(items) == 1

    assert items[0].action == PlanAction.REUSE
    assert items[0].database_id == 11
    assert items[0].values.label == "Well B"


def test_top_level_label_same_start_different_label_conflicts(
    monkeypatch,
):
    valid_from = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )

    config = ConfigModel(
        location_labels=[
            {
                "location": "well_01",
                "label": "New label",
                "valid_from": valid_from,
            }
        ]
    )

    existing_bindings = (
        PlanBinding(
            resource_type="locations",
            alias="well_01",
            resource=ExistingRef(
                resource_type="location",
                database_id=3,
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_location_labels",
        lambda location_id: (
            MetadataRow(
                database_id=11,
                values={
                    "location_id": 3,
                    "label": "Old label",
                    "valid_from": valid_from,
                    "valid_to": None,
                },
            ),
        ),
    )

    items, errors = resolve_location_label_declarations(
        config,
        location_items=(),
        existing_bindings=existing_bindings,
    )

    assert len(items) == 1
    assert items[0].action == PlanAction.REUSE
    assert items[0].database_id == 11

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT


def test_top_level_non_overlapping_label_becomes_create(
    monkeypatch,
):
    config = ConfigModel(
        location_labels=[
            {
                "location": "well_01",
                "label": "Well B",
                "valid_from": "2026-01-01T00:00:00Z",
            }
        ]
    )

    existing_bindings = (
        PlanBinding(
            resource_type="locations",
            alias="well_01",
            resource=ExistingRef(
                resource_type="location",
                database_id=3,
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_location_labels",
        lambda location_id: (
            MetadataRow(
                database_id=10,
                values={
                    "location_id": 3,
                    "label": "Well A",
                    "valid_from": datetime(
                        2025,
                        1,
                        1,
                        tzinfo=timezone.utc,
                    ),
                    "valid_to": datetime(
                        2026,
                        1,
                        1,
                        tzinfo=timezone.utc,
                    ),
                },
            ),
        ),
    )

    items, errors = resolve_location_label_declarations(
        config,
        location_items=(),
        existing_bindings=existing_bindings,
    )

    assert errors == ()
    assert len(items) == 1
    assert items[0].action == PlanAction.CREATE
    assert items[0].values.label == "Well B"


def test_top_level_label_overlapping_existing_history_conflicts(
    monkeypatch,
):
    config = ConfigModel(
        location_labels=[
            {
                "location": "well_01",
                "label": "Well B",
                "valid_from": "2025-06-01T00:00:00Z",
            }
        ]
    )

    existing_bindings = (
        PlanBinding(
            resource_type="locations",
            alias="well_01",
            resource=ExistingRef(
                resource_type="location",
                database_id=3,
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_location_labels",
        lambda location_id: (
            MetadataRow(
                database_id=10,
                values={
                    "location_id": 3,
                    "label": "Well A",
                    "valid_from": datetime(
                        2025,
                        1,
                        1,
                        tzinfo=timezone.utc,
                    ),
                    "valid_to": None,
                },
            ),
        ),
    )

    items, errors = resolve_location_label_declarations(
        config,
        location_items=(),
        existing_bindings=existing_bindings,
    )

    assert items == ()
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "location_label"


def test_top_level_labels_overlapping_planned_label_conflict():
    config = ConfigModel(
        location_labels=[
            {
                "location": "well_01",
                "label": "Well A",
                "valid_from": "2025-01-01T00:00:00Z",
                "valid_to": "2026-01-01T00:00:00Z",
            },
            {
                "location": "well_01",
                "label": "Well B",
                "valid_from": "2025-06-01T00:00:00Z",
            },
        ]
    )

    location_ref = PlannedRef(
        resource_type="location",
        plan_id="locations[0]",
    )

    existing_bindings = (
        PlanBinding(
            resource_type="locations",
            alias="well_01",
            resource=location_ref,
        ),
    )

    items, errors = resolve_location_label_declarations(
        config,
        location_items=(),
        existing_bindings=existing_bindings,
    )

    assert len(items) == 1
    assert items[0].plan_id == "location_labels[0]"
    assert items[0].action == PlanAction.CREATE

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].source_path == "location_labels[1]"


def test_top_level_label_explicit_valid_to_difference_conflicts(
    monkeypatch,
):
    valid_from = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )

    config = ConfigModel(
        location_labels=[
            {
                "location": "well_01",
                "label": "Well B",
                "valid_from": valid_from,
                "valid_to": None,
            }
        ]
    )

    existing_bindings = (
        PlanBinding(
            resource_type="locations",
            alias="well_01",
            resource=ExistingRef(
                resource_type="location",
                database_id=3,
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_location_labels",
        lambda location_id: (
            MetadataRow(
                database_id=11,
                values={
                    "location_id": 3,
                    "label": "Well B",
                    "valid_from": valid_from,
                    "valid_to": datetime(
                        2027,
                        1,
                        1,
                        tzinfo=timezone.utc,
                    ),
                },
            ),
        ),
    )

    items, errors = resolve_location_label_declarations(
        config,
        location_items=(),
        existing_bindings=existing_bindings,
    )

    assert len(items) == 1
    assert items[0].action == PlanAction.REUSE

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT


def test_deployment_reference_resolves_relational_selectors(
    monkeypatch,
):
    config = ConfigModel(
        references={
            "deployments": {
                "deployment_01": {
                    "sensor": "sensor_01",
                    "location": "well_01",
                    "variable": "water_level",
                    "valid_from": "2025-04-01T00:00:00Z",
                }
            }
        }
    )

    registry = build_alias_registry(config)

    existing_bindings = (
        PlanBinding(
            resource_type="sensors",
            alias="sensor_01",
            resource=ExistingRef(
                resource_type="sensor",
                database_id=5,
            ),
        ),
        PlanBinding(
            resource_type="locations",
            alias="well_01",
            resource=ExistingRef(
                resource_type="location",
                database_id=3,
            ),
        ),
        PlanBinding(
            resource_type="variables",
            alias="water_level",
            resource=ExistingRef(
                resource_type="variable",
                database_id=7,
            ),
        ),
    )

    def fake_find_deployments(**kwargs):
        assert kwargs["sensor_id"] == 5
        assert kwargs["location_id"] == 3
        assert kwargs["variable_id"] == 7

        return (
            MetadataRow(
                database_id=12,
                values={},
            ),
        )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        fake_find_deployments,
    )

    bindings, errors = resolve_deployment_reference_aliases(
        registry,
        existing_bindings,
    )

    assert errors == ()
    assert bindings == (
        PlanBinding(
            resource_type="deployments",
            alias="deployment_01",
            resource=ExistingRef(
                resource_type="deployment",
                database_id=12,
            ),
        ),
    )


def test_deployment_reference_reports_ambiguity(
    monkeypatch,
):
    config = ConfigModel(
        references={
            "deployments": {
                "deployment_01": {
                    "sensor": "sensor_01",
                }
            }
        }
    )

    registry = build_alias_registry(config)

    existing_bindings = (
        PlanBinding(
            resource_type="sensors",
            alias="sensor_01",
            resource=ExistingRef(
                resource_type="sensor",
                database_id=5,
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (
            MetadataRow(12, {}),
            MetadataRow(13, {}),
        ),
    )

    bindings, errors = resolve_deployment_reference_aliases(
        registry,
        existing_bindings,
    )

    assert bindings == ()
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.AMBIGUOUS
    assert errors[0].candidate_ids == (12, 13)


def test_deployment_reference_rejects_planned_sensor(
    monkeypatch,
):
    config = ConfigModel(
        references={
            "deployments": {
                "deployment_01": {
                    "sensor": "sensor_01",
                }
            }
        }
    )

    registry = build_alias_registry(config)

    existing_bindings = (
        PlanBinding(
            resource_type="sensors",
            alias="sensor_01",
            resource=PlannedRef(
                resource_type="sensor",
                plan_id="sensors[0]",
            ),
        ),
    )

    called = False

    def fake_find_deployments(**kwargs):
        nonlocal called
        called = True
        return ()

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        fake_find_deployments,
    )

    bindings, errors = resolve_deployment_reference_aliases(
        registry,
        existing_bindings,
    )

    assert bindings == ()
    assert not called
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.INVALID_REFERENCE


def test_deployment_reference_not_found(monkeypatch):
    config = ConfigModel(
        references={
            "deployments": {
                "deployment_01": {
                    "sensor": "sensor_01",
                }
            }
        }
    )

    registry = build_alias_registry(config)

    existing_bindings = (
        PlanBinding(
            resource_type="sensors",
            alias="sensor_01",
            resource=ExistingRef(
                resource_type="sensor",
                database_id=5,
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (),
    )

    bindings, errors = resolve_deployment_reference_aliases(
        registry,
        existing_bindings,
    )

    assert bindings == ()
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.NOT_FOUND


def test_deployment_reference_missing_location_alias_is_invalid():
    config = ConfigModel(
        references={
            "deployments": {
                "deployment_01": {
                    "location": "missing_location",
                }
            }
        }
    )

    registry = build_alias_registry(config)

    bindings, errors = resolve_deployment_reference_aliases(
        registry,
    )

    assert bindings == ()
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.INVALID_REFERENCE
    assert errors[0].source_path.endswith(".location")


def test_deployment_reference_partial_selector_resolves_unique_match(
    monkeypatch,
):
    config = ConfigModel(
        references={
            "deployments": {
                "deployment_01": {
                    "location": "well_01",
                }
            }
        }
    )

    registry = build_alias_registry(config)

    existing_bindings = (
        PlanBinding(
            resource_type="locations",
            alias="well_01",
            resource=ExistingRef(
                resource_type="location",
                database_id=3,
            ),
        ),
    )

    def fake_find_deployments(**kwargs):
        assert kwargs["sensor_id"] is None
        assert kwargs["location_id"] == 3
        assert kwargs["variable_id"] is None
        assert kwargs["valid_from"] is None

        return (
            MetadataRow(
                database_id=12,
                values={},
            ),
        )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        fake_find_deployments,
    )

    bindings, errors = resolve_deployment_reference_aliases(
        registry,
        existing_bindings,
    )

    assert errors == ()
    assert bindings[0].resource == ExistingRef(
        resource_type="deployment",
        database_id=12,
    )


def test_existing_deployment_becomes_reuse(monkeypatch):
    valid_from = datetime(
        2025,
        4,
        1,
        tzinfo=timezone.utc,
    )

    config = ConfigModel(
        deployments=[
            {
                "ref": "deployment_01",
                "sensor": "sensor_01",
                "location": "well_01",
                "variable": "water_level",
                "valid_from": valid_from,
            }
        ]
    )

    existing_bindings = (
        PlanBinding(
            resource_type="sensors",
            alias="sensor_01",
            resource=ExistingRef(
                resource_type="sensor",
                database_id=5,
            ),
        ),
        PlanBinding(
            resource_type="locations",
            alias="well_01",
            resource=ExistingRef(
                resource_type="location",
                database_id=3,
            ),
        ),
        PlanBinding(
            resource_type="variables",
            alias="water_level",
            resource=ExistingRef(
                resource_type="variable",
                database_id=7,
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (
            MetadataRow(
                database_id=12,
                values={
                    "sensor_id": 5,
                    "location_id": 3,
                    "variable_id": 7,
                    "valid_from": valid_from,
                    "valid_to": None,
                },
            ),
        ),
    )

    items, bindings, errors = resolve_deployment_declarations(
        config,
        existing_bindings,
    )

    assert errors == ()
    assert items[0].action == PlanAction.REUSE
    assert items[0].database_id == 12
    assert bindings[0].resource == ExistingRef(
        resource_type="deployment",
        database_id=12,
    )


def test_deployment_with_planned_sensor_becomes_create(
    monkeypatch,
):
    config = ConfigModel(
        deployments=[
            {
                "ref": "deployment_01",
                "sensor": "sensor_01",
                "location": "well_01",
                "variable": "water_level",
                "valid_from": "2025-04-01T00:00:00Z",
            }
        ]
    )

    existing_bindings = (
        PlanBinding(
            resource_type="sensors",
            alias="sensor_01",
            resource=PlannedRef(
                resource_type="sensor",
                plan_id="sensors[0]",
            ),
        ),
        PlanBinding(
            resource_type="locations",
            alias="well_01",
            resource=ExistingRef(
                resource_type="location",
                database_id=3,
            ),
        ),
        PlanBinding(
            resource_type="variables",
            alias="water_level",
            resource=ExistingRef(
                resource_type="variable",
                database_id=7,
            ),
        ),
    )

    called = False

    def fake_find_deployments(**kwargs):
        nonlocal called
        called = True
        return ()

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        fake_find_deployments,
    )

    items, bindings, errors = resolve_deployment_declarations(
        config,
        existing_bindings,
    )

    assert errors == ()
    assert not called
    assert items[0].action == PlanAction.CREATE
    assert bindings[0].resource == PlannedRef(
        resource_type="deployment",
        plan_id="deployments[0]",
    )


def test_deployment_overlapping_existing_history_conflicts(
    monkeypatch,
):
    config = ConfigModel(
        deployments=[
            {
                "sensor": "sensor_01",
                "location": "well_02",
                "variable": "water_level",
                "valid_from": "2025-06-01T00:00:00Z",
            }
        ]
    )

    existing_bindings = (
        PlanBinding(
            resource_type="sensors",
            alias="sensor_01",
            resource=ExistingRef(
                resource_type="sensor",
                database_id=5,
            ),
        ),
        PlanBinding(
            resource_type="locations",
            alias="well_02",
            resource=ExistingRef(
                resource_type="location",
                database_id=4,
            ),
        ),
        PlanBinding(
            resource_type="variables",
            alias="water_level",
            resource=ExistingRef(
                resource_type="variable",
                database_id=7,
            ),
        ),
    )

    existing_start = datetime(
        2025,
        1,
        1,
        tzinfo=timezone.utc,
    )

    def fake_find_deployments(**kwargs):
        if "location_id" in kwargs:
            return ()

        return (
            MetadataRow(
                database_id=12,
                values={
                    "sensor_id": 5,
                    "location_id": 3,
                    "variable_id": 7,
                    "valid_from": existing_start,
                    "valid_to": None,
                },
            ),
        )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        fake_find_deployments,
    )

    items, bindings, errors = resolve_deployment_declarations(
        config,
        existing_bindings,
    )

    assert items == ()
    assert bindings == ()
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT


def test_deployment_overlapping_planned_deployment_conflicts(
    monkeypatch,
):
    config = ConfigModel(
        deployments=[
            {
                "sensor": "sensor_01",
                "location": "well_01",
                "variable": "water_level",
                "valid_from": "2025-01-01T00:00:00Z",
                "valid_to": "2026-01-01T00:00:00Z",
            },
            {
                "sensor": "sensor_01",
                "location": "well_02",
                "variable": "water_level",
                "valid_from": "2025-06-01T00:00:00Z",
            },
        ]
    )

    sensor_ref = PlannedRef(
        resource_type="sensor",
        plan_id="sensors[0]",
    )

    existing_bindings = (
        PlanBinding(
            resource_type="sensors",
            alias="sensor_01",
            resource=sensor_ref,
        ),
        PlanBinding(
            resource_type="locations",
            alias="well_01",
            resource=ExistingRef(
                resource_type="location",
                database_id=3,
            ),
        ),
        PlanBinding(
            resource_type="locations",
            alias="well_02",
            resource=ExistingRef(
                resource_type="location",
                database_id=4,
            ),
        ),
        PlanBinding(
            resource_type="variables",
            alias="water_level",
            resource=ExistingRef(
                resource_type="variable",
                database_id=7,
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (),
    )

    items, _, errors = resolve_deployment_declarations(
        config,
        existing_bindings,
    )

    assert len(items) == 1
    assert items[0].action == PlanAction.CREATE

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].source_path == "deployments[1]"


def test_new_deployment_with_existing_dependencies_becomes_create(
    monkeypatch,
):
    config = ConfigModel(
        deployments=[
            {
                "ref": "deployment_01",
                "sensor": "sensor_01",
                "location": "well_01",
                "variable": "water_level",
                "valid_from": "2025-04-01T00:00:00Z",
            }
        ]
    )

    existing_bindings = (
        PlanBinding(
            resource_type="sensors",
            alias="sensor_01",
            resource=ExistingRef(
                resource_type="sensor",
                database_id=5,
            ),
        ),
        PlanBinding(
            resource_type="locations",
            alias="well_01",
            resource=ExistingRef(
                resource_type="location",
                database_id=3,
            ),
        ),
        PlanBinding(
            resource_type="variables",
            alias="water_level",
            resource=ExistingRef(
                resource_type="variable",
                database_id=7,
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (),
    )

    items, bindings, errors = resolve_deployment_declarations(
        config,
        existing_bindings,
    )

    assert errors == ()
    assert len(items) == 1
    assert items[0].action == PlanAction.CREATE
    assert bindings[0].resource == PlannedRef(
        resource_type="deployment",
        plan_id="deployments[0]",
    )


def test_existing_deployment_explicit_valid_to_difference_conflicts(
    monkeypatch,
):
    valid_from = datetime(
        2025,
        4,
        1,
        tzinfo=timezone.utc,
    )

    config = ConfigModel(
        deployments=[
            {
                "sensor": "sensor_01",
                "location": "well_01",
                "variable": "water_level",
                "valid_from": valid_from,
                "valid_to": None,
            }
        ]
    )

    existing_bindings = (
        PlanBinding(
            resource_type="sensors",
            alias="sensor_01",
            resource=ExistingRef(
                resource_type="sensor",
                database_id=5,
            ),
        ),
        PlanBinding(
            resource_type="locations",
            alias="well_01",
            resource=ExistingRef(
                resource_type="location",
                database_id=3,
            ),
        ),
        PlanBinding(
            resource_type="variables",
            alias="water_level",
            resource=ExistingRef(
                resource_type="variable",
                database_id=7,
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (
            MetadataRow(
                database_id=12,
                values={
                    "sensor_id": 5,
                    "location_id": 3,
                    "variable_id": 7,
                    "valid_from": valid_from,
                    "valid_to": datetime(
                        2026,
                        1,
                        1,
                        tzinfo=timezone.utc,
                    ),
                },
            ),
        ),
    )

    items, _, errors = resolve_deployment_declarations(
        config,
        existing_bindings,
    )

    assert len(items) == 1
    assert items[0].action == PlanAction.REUSE

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT


def test_deployment_adjacent_to_existing_history_becomes_create(
    monkeypatch,
):
    new_start = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )

    config = ConfigModel(
        deployments=[
            {
                "sensor": "sensor_01",
                "location": "well_02",
                "variable": "water_level",
                "valid_from": new_start,
            }
        ]
    )

    existing_bindings = (
        PlanBinding(
            resource_type="sensors",
            alias="sensor_01",
            resource=ExistingRef(
                resource_type="sensor",
                database_id=5,
            ),
        ),
        PlanBinding(
            resource_type="locations",
            alias="well_02",
            resource=ExistingRef(
                resource_type="location",
                database_id=4,
            ),
        ),
        PlanBinding(
            resource_type="variables",
            alias="water_level",
            resource=ExistingRef(
                resource_type="variable",
                database_id=7,
            ),
        ),
    )

    def fake_find_deployments(**kwargs):
        if kwargs.get("location_id") is not None:
            return ()

        return (
            MetadataRow(
                database_id=12,
                values={
                    "sensor_id": 5,
                    "location_id": 3,
                    "variable_id": 7,
                    "valid_from": datetime(
                        2025,
                        1,
                        1,
                        tzinfo=timezone.utc,
                    ),
                    "valid_to": new_start,
                },
            ),
        )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        fake_find_deployments,
    )

    items, _, errors = resolve_deployment_declarations(
        config,
        existing_bindings,
    )

    assert errors == ()
    assert len(items) == 1
    assert items[0].action == PlanAction.CREATE


def test_deployment_missing_relationship_bindings_reports_all_errors(
    monkeypatch,
):
    config = ConfigModel(
        deployments=[
            {
                "sensor": "missing_sensor",
                "location": "missing_location",
                "variable": "missing_variable",
                "valid_from": "2025-04-01T00:00:00Z",
            }
        ]
    )

    called = False

    def fake_find_deployments(**kwargs):
        nonlocal called
        called = True
        return ()

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        fake_find_deployments,
    )

    items, bindings, errors = resolve_deployment_declarations(
        config,
    )

    assert items == ()
    assert bindings == ()
    assert not called

    assert len(errors) == 3
    assert all(
        error.code == PlanErrorCode.INVALID_REFERENCE
        for error in errors
    )

    assert {
        error.source_path
        for error in errors
    } == {
        "deployments[0].sensor",
        "deployments[0].location",
        "deployments[0].variable",
    }


def test_resolve_metadata_config_empty_config():
    plan = resolve_metadata_config(ConfigModel())

    assert plan.metadata_items == ()
    assert plan.raw_items == ()
    assert plan.bindings == ()
    assert plan.errors == ()
    assert plan.warnings == ()
    assert plan.can_apply


def test_resolve_metadata_config_planned_dependency_chain(
    monkeypatch,
):
    config = ConfigModel(
        sites=[
            {
                "ref": "sandhagen",
                "site_code": "SAN",
                "name": "Sandhagen",
            }
        ],
        location_types=[
            {
                "ref": "well",
                "type": "well",
            }
        ],
        sensor_types=[
            {
                "ref": "pressure",
                "type": "pressure",
            }
        ],
        variables=[
            {
                "ref": "water_level",
                "variable": "water_level",
            }
        ],
        sensor_models=[
            {
                "ref": "cs451",
                "manufacturer": "Campbell Scientific",
                "model": "CS451",
                "sensor_type": "pressure",
            }
        ],
        sensors=[
            {
                "ref": "sensor_01",
                "sensor_model": "cs451",
                "serial_number": "123456",
            }
        ],
        locations=[
            {
                "ref": "well_01",
                "site": "sandhagen",
                "location_type": "well",
                "initial_label": {
                    "label": "Well 01",
                    "valid_from": "2025-04-01T00:00:00Z",
                },
            }
        ],
        deployments=[
            {
                "ref": "deployment_01",
                "sensor": "sensor_01",
                "location": "well_01",
                "variable": "water_level",
                "valid_from": "2025-04-01T00:00:00Z",
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
        "find_location_type",
        lambda type_: None,
    )
    monkeypatch.setattr(
        metadata,
        "find_sensor_type",
        lambda type_: None,
    )
    monkeypatch.setattr(
        metadata,
        "find_variable",
        lambda variable: None,
    )
    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (),
    )
    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (),
    )
    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (),
    )
    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (),
    )

    plan = resolve_metadata_config(config)

    assert plan.errors == ()
    assert plan.can_apply

    actions = {
        item.plan_id: item.action
        for item in plan.metadata_items
    }

    assert actions == {
        "sites[0]": PlanAction.CREATE,
        "location_types[0]": PlanAction.CREATE,
        "sensor_types[0]": PlanAction.CREATE,
        "variables[0]": PlanAction.CREATE,
        "sensor_models[0]": PlanAction.CREATE,
        "sensors[0]": PlanAction.CREATE,
        "locations[0]": PlanAction.CREATE,
        "locations[0].initial_label": PlanAction.CREATE,
        "deployments[0]": PlanAction.CREATE,
    }

    deployment = next(
        item
        for item in plan.metadata_items
        if item.plan_id == "deployments[0]"
    )

    assert deployment.values.sensor == PlannedRef(
        resource_type="sensor",
        plan_id="sensors[0]",
    )
    assert deployment.values.location == PlannedRef(
        resource_type="location",
        plan_id="locations[0]",
    )
    assert deployment.values.variable == PlannedRef(
        resource_type="variable",
        plan_id="variables[0]",
    )


def test_resolve_metadata_config_existing_roots_with_planned_dependents(
    monkeypatch,
):
    config = ConfigModel(
        sites=[
            {
                "ref": "sandhagen",
                "site_code": "SAN",
                "name": "Sandhagen",
            }
        ],
        location_types=[
            {
                "ref": "well",
                "type": "well",
            }
        ],
        sensor_types=[
            {
                "ref": "pressure",
                "type": "pressure",
            }
        ],
        variables=[
            {
                "ref": "water_level",
                "variable": "water_level",
            }
        ],
        sensor_models=[
            {
                "ref": "cs451",
                "manufacturer": "Campbell Scientific",
                "model": "CS451",
                "sensor_type": "pressure",
            }
        ],
        sensors=[
            {
                "ref": "sensor_01",
                "sensor_model": "cs451",
                "serial_number": "123456",
            }
        ],
        locations=[
            {
                "ref": "well_01",
                "site": "sandhagen",
                "location_type": "well",
                "initial_label": {
                    "label": "Well 01",
                    "valid_from": "2025-04-01T00:00:00Z",
                },
            }
        ],
        deployments=[
            {
                "ref": "deployment_01",
                "sensor": "sensor_01",
                "location": "well_01",
                "variable": "water_level",
                "valid_from": "2025-04-01T00:00:00Z",
            }
        ],
    )

    # Existing simple resources.
    monkeypatch.setattr(
        metadata,
        "find_site",
        lambda site_code: MetadataRow(
            database_id=1,
            values={
                "site_code": "SAN",
                "name": "Sandhagen",
                "description": None,
                "latitude": None,
                "longitude": None,
                "parent_id": None,
            },
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_location_type",
        lambda type_: MetadataRow(
            database_id=2,
            values={
                "type": "well",
                "description": None,
            },
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_variable",
        lambda variable: MetadataRow(
            database_id=7,
            values={
                "variable": "water_level",
                "derived": False,
                "description": None,
            },
        ),
    )

    # New resources.
    monkeypatch.setattr(
        metadata,
        "find_sensor_type",
        lambda type_: None,
    )
    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (),
    )
    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (),
    )
    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (),
    )
    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (),
    )

    plan = resolve_metadata_config(config)

    assert plan.errors == ()
    assert plan.can_apply

    actions = {
        item.plan_id: item.action
        for item in plan.metadata_items
    }

    assert actions == {
        "sites[0]": PlanAction.REUSE,
        "location_types[0]": PlanAction.REUSE,
        "sensor_types[0]": PlanAction.CREATE,
        "variables[0]": PlanAction.REUSE,
        "sensor_models[0]": PlanAction.CREATE,
        "sensors[0]": PlanAction.CREATE,
        "locations[0]": PlanAction.CREATE,
        "locations[0].initial_label": PlanAction.CREATE,
        "deployments[0]": PlanAction.CREATE,
    }


def test_resolve_metadata_config_propagates_resolution_errors(
    monkeypatch,
):
    config = ConfigModel(
        references={
            "sensors": {
                "missing_sensor": {
                    "serial_number": "DOES_NOT_EXIST",
                }
            },
            "locations": {
                "well_01": {
                    "initial_label": "Well 01",
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
                "sensor": "missing_sensor",
                "location": "well_01",
                "variable": "water_level",
                "valid_from": "2025-04-01T00:00:00Z",
            }
        ],
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (),
    )

    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (
            MetadataRow(
                database_id=3,
                values={
                    "site_id": 1,
                    "location_type_id": 2,
                    "latitude": None,
                    "longitude": None,
                    "height_above_ground": None,
                    "azimuth": None,
                    "initial_label": "Well 01",
                    "initial_label_valid_from": None,
                    "initial_label_valid_to": None,
                },
            ),
        ),
    )

    monkeypatch.setattr(
        metadata,
        "find_variable",
        lambda variable: MetadataRow(
            database_id=7,
            values={
                "variable": "water_level",
                "derived": False,
                "description": None,
            },
        ),
    )

    plan = resolve_metadata_config(config)

    assert not plan.can_apply
    assert len(plan.errors) == 2

    assert not any(
         item.resource_type == "deployment"
         for item in plan.metadata_items
    )
    
    assert {
        error.code
        for error in plan.errors
    } == {
        PlanErrorCode.NOT_FOUND,
        PlanErrorCode.INVALID_REFERENCE,
    }

    not_found = next(
        error
        for error in plan.errors
        if error.code == PlanErrorCode.NOT_FOUND
    )

    assert not_found.resource_type == "sensors"

    invalid_reference = next(
        error
        for error in plan.errors
        if error.code == PlanErrorCode.INVALID_REFERENCE
    )

    assert invalid_reference.resource_type == "deployment"
    assert invalid_reference.source_path == "deployments[0].sensor"

    assert ExistingRef(
        resource_type="location",
        database_id=3,
    ) in {
        binding.resource
        for binding in plan.bindings
    }

    assert ExistingRef(
        resource_type="variable",
        database_id=7,
    ) in {
        binding.resource
        for binding in plan.bindings
    }



