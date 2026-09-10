from dendroflow.configuration import ConfigModel, metadata, validate_config
from dendroflow.configuration.metadata import MetadataRow
from dendroflow.configuration.plan import (
    ExistingRef,
    PlanAction,
    PlanErrorCode,
    PlannedRef,
)
from dendroflow.configuration.resolver import (
    DeclarationAlias,
    PlanBinding,
    ReferenceAlias,
    build_alias_registry,
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

