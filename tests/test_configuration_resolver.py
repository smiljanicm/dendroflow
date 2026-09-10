from dendroflow.configuration import ConfigModel, metadata, validate_config
from dendroflow.configuration.metadata import MetadataRow
from dendroflow.configuration.plan import ExistingRef, PlanErrorCode
from dendroflow.configuration.resolver import (
    DeclarationAlias,
    ReferenceAlias,
    build_alias_registry,
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

