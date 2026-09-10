from dendroflow.configuration import ConfigModel, validate_config
from dendroflow.configuration.resolver import (
    DeclarationAlias,
    ReferenceAlias,
    build_alias_registry,
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


