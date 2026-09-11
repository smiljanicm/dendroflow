from ..models import ConfigModel
from ..plan import PlanBinding, PlanError, ResolvedPlan, ResolvedPlanItem
from ..validation import validate_config
from .aliases import build_alias_registry
from .metadata import (
    resolve_deployment_declarations,
    resolve_deployment_reference_aliases,
    resolve_location_declarations,
    resolve_location_label_declarations,
    resolve_location_reference_aliases,
    resolve_sensor_declarations,
    resolve_sensor_model_declarations,
    resolve_sensor_model_reference_aliases,
    resolve_sensor_reference_aliases,
    resolve_simple_declarations,
    resolve_simple_reference_aliases,
)
from .raw import (
    resolve_file_declarations,
    resolve_interface_declarations,
)


def resolve_metadata_config(
    config: ConfigModel,
) -> ResolvedPlan:
    """Resolve validated CONFIG against dendroflow_metadata."""

    validate_config(config)

    registry = build_alias_registry(config)

    metadata_items: list[ResolvedPlanItem] = []
    bindings: list[PlanBinding] = []
    errors: list[PlanError] = []

    # Simple resources:
    # sites, location types, sensor types, variables.
    new_bindings, new_errors = resolve_simple_reference_aliases(
        registry
    )
    bindings.extend(new_bindings)
    errors.extend(new_errors)

    new_items, new_bindings, new_errors = (
        resolve_simple_declarations(
            config,
            existing_bindings=tuple(bindings),
        )
    )
    metadata_items.extend(new_items)
    bindings.extend(new_bindings)
    errors.extend(new_errors)

    # Sensor models.
    new_bindings, new_errors = (
        resolve_sensor_model_reference_aliases(
            registry
        )
    )
    bindings.extend(new_bindings)
    errors.extend(new_errors)

    new_items, new_bindings, new_errors = (
        resolve_sensor_model_declarations(
            config,
            existing_bindings=tuple(bindings),
        )
    )
    metadata_items.extend(new_items)
    bindings.extend(new_bindings)
    errors.extend(new_errors)

    # Sensors.
    new_bindings, new_errors = (
        resolve_sensor_reference_aliases(
            registry,
            existing_bindings=tuple(bindings),
        )
    )
    bindings.extend(new_bindings)
    errors.extend(new_errors)

    new_items, new_bindings, new_errors = (
        resolve_sensor_declarations(
            config,
            existing_bindings=tuple(bindings),
        )
    )
    metadata_items.extend(new_items)
    bindings.extend(new_bindings)
    errors.extend(new_errors)

    # Locations.
    new_bindings, new_errors = (
        resolve_location_reference_aliases(
            registry,
            existing_bindings=tuple(bindings),
        )
    )
    bindings.extend(new_bindings)
    errors.extend(new_errors)

    new_items, new_bindings, new_errors = (
        resolve_location_declarations(
            config,
            existing_bindings=tuple(bindings),
        )
    )
    metadata_items.extend(new_items)
    bindings.extend(new_bindings)
    errors.extend(new_errors)

    # Location labels.
    location_items = tuple(
        item
        for item in metadata_items
        if item.resource_type == "location"
    )

    new_items, new_errors = (
        resolve_location_label_declarations(
            config,
            location_items=location_items,
            existing_bindings=tuple(bindings),
        )
    )
    metadata_items.extend(new_items)
    errors.extend(new_errors)

    # Deployments.
    new_bindings, new_errors = (
        resolve_deployment_reference_aliases(
            registry,
            existing_bindings=tuple(bindings),
        )
    )
    bindings.extend(new_bindings)
    errors.extend(new_errors)

    new_items, new_bindings, new_errors = (
        resolve_deployment_declarations(
            config,
            existing_bindings=tuple(bindings),
        )
    )
    metadata_items.extend(new_items)
    bindings.extend(new_bindings)
    errors.extend(new_errors)

    return ResolvedPlan(
        metadata_items=tuple(metadata_items),
        raw_items=(),
        bindings=tuple(bindings),
        errors=tuple(errors),
        warnings=(),
    )


def resolve_raw_config(
    config: ConfigModel,
    existing_bindings: tuple[PlanBinding, ...] = (),
) -> ResolvedPlan:
    """Resolve validated CONFIG against dendroflow_raw."""

    validate_config(config)

    raw_items: list[ResolvedPlanItem] = []
    bindings: list[PlanBinding] = []
    errors: list[PlanError] = []

    # Files.
    file_items, file_bindings, file_errors = (
        resolve_file_declarations(config)
    )
    raw_items.extend(file_items)
    bindings.extend(file_bindings)
    errors.extend(file_errors)

    # Interfaces.
    interface_items, interface_errors = (
        resolve_interface_declarations(
            config,
            file_items=file_items,
            existing_bindings=existing_bindings,
        )
    )
    raw_items.extend(interface_items)
    errors.extend(interface_errors)

    return ResolvedPlan(
        metadata_items=(),
        raw_items=tuple(raw_items),
        bindings=tuple(bindings),
        errors=tuple(errors),
        warnings=(),
    )

