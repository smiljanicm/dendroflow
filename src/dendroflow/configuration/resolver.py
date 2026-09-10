from dataclasses import dataclass
from datetime import datetime

from . import metadata
from .metadata import MetadataRow
from .models import ConfigModel, LookupConfig
from .plan import (
    ExistingRef,
    PlanAction,
    PlanBinding,
    PlanError,
    PlanErrorCode,
    PlannedRef,
    ResolvedLocationLabelValues,
    ResolvedLocationTypeValues,
    ResolvedLocationValues,
    ResolvedPlanItem,
    ResolvedSensorModelValues,
    ResolvedSensorTypeValues,
    ResolvedSensorValues,
    ResolvedSiteValues,
    ResolvedVariableValues,
    ResourceRef,
)


@dataclass(frozen=True)
class DeclarationAlias:
    """Alias referring to a resource declaration in this configuration."""

    resource_type: str
    alias: str
    source_path: str
    declaration_index: int


@dataclass(frozen=True)
class ReferenceAlias:
    """Alias referring to an existing-resource lookup."""

    resource_type: str
    alias: str
    source_path: str
    selector: LookupConfig


LocalAlias = DeclarationAlias | ReferenceAlias


@dataclass(frozen=True)
class AliasRegistry:
    """Local YAML namespace used during configuration resolution."""

    entries: tuple[LocalAlias, ...] = ()

    def get(
        self,
        resource_type: str,
        alias: str,
    ) -> LocalAlias | None:
        for entry in self.entries:
            if (
                entry.resource_type == resource_type
                and entry.alias == alias
            ):
                return entry

        return None

    def aliases(self, resource_type: str) -> tuple[str, ...]:
        return tuple(
            entry.alias
            for entry in self.entries
            if entry.resource_type == resource_type
        )


def build_alias_registry(config: ConfigModel) -> AliasRegistry:
    """Build the local alias namespace for a validated configuration."""

    entries: list[LocalAlias] = []

    resource_types = (
        "sites",
        "location_types",
        "sensor_types",
        "variables",
        "sensor_models",
        "sensors",
        "locations",
        "deployments",
        "files",
    )

    for resource_type in resource_types:
        declarations = getattr(config, resource_type)

        for index, declaration in enumerate(declarations):
            if declaration.ref is None:
                continue

            entries.append(
                DeclarationAlias(
                    resource_type=resource_type,
                    alias=declaration.ref,
                    source_path=f"{resource_type}[{index}].ref",
                    declaration_index=index,
                )
            )

        references = getattr(config.references, resource_type)

        for alias in sorted(references):
            entries.append(
                ReferenceAlias(
                    resource_type=resource_type,
                    alias=alias,
                    source_path=(
                        f"references.{resource_type}.{alias}"
                    ),
                    selector=references[alias],
                )
            )

    return AliasRegistry(entries=tuple(entries))


def resolve_simple_reference_aliases(
    registry: AliasRegistry,
) -> tuple[tuple[PlanBinding, ...], tuple[PlanError, ...]]:
    """Resolve simple METADATA reference aliases against PostgreSQL."""

    bindings: list[PlanBinding] = []
    errors: list[PlanError] = []

    for entry in registry.entries:
        if not isinstance(entry, ReferenceAlias):
            continue

        selector_field = _SIMPLE_REFERENCE_FIELDS.get(
            entry.resource_type
        )

        if selector_field is None:
            continue

        selector_value = getattr(entry.selector, selector_field)

        if selector_value is None:
            errors.append(
                PlanError(
                    code=PlanErrorCode.INVALID_REFERENCE,
                    resource_type=entry.resource_type,
                    source_path=entry.source_path,
                    message=(
                        f"{entry.resource_type} reference must specify "
                        f"{selector_field}"
                    ),
                )
            )
            continue

        row = _find_simple_metadata(
            entry.resource_type,
            selector_value,
        )

        if row is None:
            errors.append(
                PlanError(
                    code=PlanErrorCode.NOT_FOUND,
                    resource_type=entry.resource_type,
                    source_path=entry.source_path,
                    message=(
                        f"{entry.resource_type} resource not found "
                        f"for {selector_field}={selector_value!r}"
                    ),
                )
            )
            continue

        bindings.append(
            PlanBinding(
                resource_type=entry.resource_type,
                alias=entry.alias,
                resource=ExistingRef(
                    resource_type=_singular_resource_type(
                        entry.resource_type
                    ),
                    database_id=row.database_id,
                ),
            )
        )

    return tuple(bindings), tuple(errors)


def _singular_resource_type(resource_type: str) -> str:
    names = {
        "sites": "site",
        "location_types": "location_type",
        "sensor_types": "sensor_type",
        "variables": "variable",
    }

    return names[resource_type]


_SIMPLE_REFERENCE_FIELDS = {
    "sites": "site_code",
    "location_types": "type",
    "sensor_types": "type",
    "variables": "variable",
}


def _find_simple_metadata(
    resource_type: str,
    value: str,
) -> MetadataRow | None:
    if resource_type == "sites":
        return metadata.find_site(value)

    if resource_type == "location_types":
        return metadata.find_location_type(value)

    if resource_type == "sensor_types":
        return metadata.find_sensor_type(value)

    if resource_type == "variables":
        return metadata.find_variable(value)

    raise ValueError(
        f"unsupported simple metadata resource type: {resource_type}"
    )


# Main functions for resolving simple declarations


def resolve_simple_declarations(
    config: ConfigModel,
    existing_bindings: tuple[PlanBinding, ...] = (),
) -> tuple[
    tuple[ResolvedPlanItem, ...],
    tuple[PlanBinding, ...],
    tuple[PlanError, ...],
]:
    """Resolve simple METADATA declarations against PostgreSQL."""

    items: list[ResolvedPlanItem] = []
    bindings: list[PlanBinding] = []
    errors: list[PlanError] = []

    targets: dict[tuple[str, int], ResourceRef] = {}
    rows: dict[tuple[str, int], MetadataRow | None] = {}

    resource_types = (
        "sites",
        "location_types",
        "sensor_types",
        "variables",
    )

    # Pass 1: determine whether each declaration already exists.
    for resource_type in resource_types:
        selector_field = _SIMPLE_REFERENCE_FIELDS[resource_type]
        declarations = getattr(config, resource_type)

        for index, declaration in enumerate(declarations):
            key = (resource_type, index)
            plan_id = f"{resource_type}[{index}]"
            selector_value = getattr(declaration, selector_field)

            row = _find_simple_metadata(
                resource_type,
                selector_value,
            )
            rows[key] = row

            if row is None:
                resource = PlannedRef(
                    resource_type=_singular_resource_type(
                        resource_type
                    ),
                    plan_id=plan_id,
                )
            else:
                resource = ExistingRef(
                    resource_type=_singular_resource_type(
                        resource_type
                    ),
                    database_id=row.database_id,
                )

            targets[key] = resource

            if declaration.ref is not None:
                bindings.append(
                    PlanBinding(
                        resource_type=resource_type,
                        alias=declaration.ref,
                        resource=resource,
                    )
                )

    all_bindings = existing_bindings + tuple(bindings)

    # Pass 2: build database-oriented plan values.
    for resource_type in resource_types:
        declarations = getattr(config, resource_type)

        for index, declaration in enumerate(declarations):
            key = (resource_type, index)
            row = rows[key]
            plan_id = f"{resource_type}[{index}]"

            values, declaration_errors = _build_simple_values(
                resource_type,
                declaration,
                row,
                all_bindings,
                plan_id,
            )

            errors.extend(declaration_errors)

            if values is None:
                continue

            items.append(
                ResolvedPlanItem(
                    plan_id=plan_id,
                    resource_type=_singular_resource_type(
                        resource_type
                    ),
                    action=(
                        PlanAction.CREATE
                        if row is None
                        else PlanAction.REUSE
                    ),
                    database_id=(
                        None
                        if row is None
                        else row.database_id
                    ),
                    values=values,
                    source_path=plan_id,
                )
            )

    return tuple(items), tuple(bindings), tuple(errors)


def _build_simple_values(
    resource_type: str,
    declaration: object,
    row: MetadataRow | None,
    bindings: tuple[PlanBinding, ...],
    source_path: str,
) -> tuple[object | None, tuple[PlanError, ...]]:
    if resource_type == "sites":
        return _build_site_values(
            declaration,
            row,
            bindings,
            source_path,
        )

    if resource_type == "location_types":
        if row is None:
            return (
                ResolvedLocationTypeValues(
                    type=declaration.type,
                    description=declaration.description,
                ),
                (),
            )

        errors = _compare_explicit_fields(
            declaration,
            row,
            ("description",),
            source_path,
            "location_type",
        )

        return (
            ResolvedLocationTypeValues(
                type=row.values["type"],
                description=row.values["description"],
            ),
            errors,
        )

    if resource_type == "sensor_types":
        if row is None:
            return (
                ResolvedSensorTypeValues(
                    type=declaration.type,
                    description=declaration.description,
                ),
                (),
            )

        errors = _compare_explicit_fields(
            declaration,
            row,
            ("description",),
            source_path,
            "sensor_type",
        )

        return (
            ResolvedSensorTypeValues(
                type=row.values["type"],
                description=row.values["description"],
            ),
            errors,
        )

    if resource_type == "variables":
        if row is None:
            return (
                ResolvedVariableValues(
                    variable=declaration.variable,
                    derived=declaration.derived,
                    description=declaration.description,
                ),
                (),
            )

        errors = list(
            _compare_explicit_fields(
                declaration,
                row,
                ("description",),
                source_path,
                "variable",
            )
        )

        if declaration.derived != row.values["derived"]:
            errors.append(
                _conflict(
                    source_path,
                    "variable",
                    "derived",
                    row.values["derived"],
                    declaration.derived,
                )
            )

        return (
            ResolvedVariableValues(
                variable=row.values["variable"],
                derived=row.values["derived"],
                description=row.values["description"],
            ),
            tuple(errors),
        )

    raise ValueError(
        f"unsupported simple metadata resource type: {resource_type}"
    )


def _build_site_values(
    declaration: object,
    row: MetadataRow | None,
    bindings: tuple[PlanBinding, ...],
    source_path: str,
) -> tuple[ResolvedSiteValues | None, tuple[PlanError, ...]]:
    parent: ResourceRef | None = None

    if declaration.parent is not None:
        binding = _find_binding(
            bindings,
            "sites",
            declaration.parent,
        )

        if binding is None:
            return (
                None,
                (
                    PlanError(
                        code=PlanErrorCode.INVALID_REFERENCE,
                        resource_type="site",
                        source_path=f"{source_path}.parent",
                        message=(
                            "unable to resolve site parent "
                            f"{declaration.parent!r}"
                        ),
                    ),
                ),
            )

        parent = binding.resource

    if row is None:
        return (
            ResolvedSiteValues(
                site_code=declaration.site_code,
                name=declaration.name,
                description=declaration.description,
                latitude=declaration.latitude,
                longitude=declaration.longitude,
                parent=parent,
            ),
            (),
        )

    errors = list(
        _compare_explicit_fields(
            declaration,
            row,
            (
                "description",
                "latitude",
                "longitude",
            ),
            source_path,
            "site",
        )
    )

    if declaration.name != row.values["name"]:
        errors.append(
            _conflict(
                source_path,
                "site",
                "name",
                row.values["name"],
                declaration.name,
            )
        )

    existing_parent_id = row.values["parent_id"]

    if "parent" in declaration.model_fields_set:
        requested_parent_id = (
            parent.database_id
            if isinstance(parent, ExistingRef)
            else None
        )

        parent_matches = (
            isinstance(parent, ExistingRef)
            and requested_parent_id == existing_parent_id
        ) or (
            parent is None
            and existing_parent_id is None
        )

        if not parent_matches:
            errors.append(
                _conflict(
                    source_path,
                    "site",
                    "parent",
                    existing_parent_id,
                    parent,
                )
            )

    existing_parent = (
        ExistingRef(
            resource_type="site",
            database_id=existing_parent_id,
        )
        if existing_parent_id is not None
        else None
    )

    return (
        ResolvedSiteValues(
            site_code=row.values["site_code"],
            name=row.values["name"],
            description=row.values["description"],
            latitude=row.values["latitude"],
            longitude=row.values["longitude"],
            parent=existing_parent,
        ),
        tuple(errors),
    )


def _find_binding(
    bindings: tuple[PlanBinding, ...],
    resource_type: str,
    alias: str,
) -> PlanBinding | None:
    for binding in bindings:
        if (
            binding.resource_type == resource_type
            and binding.alias == alias
        ):
            return binding

    return None


def _compare_explicit_fields(
    declaration: object,
    row: MetadataRow,
    fields: tuple[str, ...],
    source_path: str,
    resource_type: str,
) -> tuple[PlanError, ...]:
    errors: list[PlanError] = []

    for field in fields:
        if field not in declaration.model_fields_set:
            continue

        requested = getattr(declaration, field)
        existing = row.values[field]

        if requested != existing:
            errors.append(
                _conflict(
                    source_path,
                    resource_type,
                    field,
                    existing,
                    requested,
                )
            )

    return tuple(errors)


def _conflict(
    source_path: str,
    resource_type: str,
    field: str,
    existing: object,
    requested: object,
) -> PlanError:
    return PlanError(
        code=PlanErrorCode.CONFLICT,
        resource_type=resource_type,
        source_path=f"{source_path}.{field}",
        message=(
            f"{field} differs from existing resource: "
            f"existing={existing!r}, requested={requested!r}"
        ),
    )


# Metadata resolutions for sensors


def resolve_sensor_model_reference_aliases(
    registry: AliasRegistry,
) -> tuple[tuple[PlanBinding, ...], tuple[PlanError, ...]]:
    """Resolve sensor-model reference aliases against PostgreSQL."""

    bindings: list[PlanBinding] = []
    errors: list[PlanError] = []

    for entry in registry.entries:
        if not isinstance(entry, ReferenceAlias):
            continue

        if entry.resource_type != "sensor_models":
            continue

        rows = metadata.find_sensor_models(
            manufacturer=entry.selector.manufacturer,
            model=entry.selector.model,
        )

        if not rows:
            errors.append(
                PlanError(
                    code=PlanErrorCode.NOT_FOUND,
                    resource_type="sensor_models",
                    source_path=entry.source_path,
                    message="sensor model resource not found",
                )
            )
            continue

        if len(rows) > 1:
            errors.append(
                PlanError(
                    code=PlanErrorCode.AMBIGUOUS,
                    resource_type="sensor_models",
                    source_path=entry.source_path,
                    message=(
                        "sensor model reference matched multiple resources"
                    ),
                    candidate_ids=tuple(
                        row.database_id for row in rows
                    ),
                )
            )
            continue

        row = rows[0]

        bindings.append(
            PlanBinding(
                resource_type="sensor_models",
                alias=entry.alias,
                resource=ExistingRef(
                    resource_type="sensor_model",
                    database_id=row.database_id,
                ),
            )
        )

    return tuple(bindings), tuple(errors)


def resolve_sensor_model_declarations(
    config: ConfigModel,
    existing_bindings: tuple[PlanBinding, ...] = (),
) -> tuple[
    tuple[ResolvedPlanItem, ...],
    tuple[PlanBinding, ...],
    tuple[PlanError, ...],
]:
    """Resolve sensor-model declarations against PostgreSQL."""

    items: list[ResolvedPlanItem] = []
    bindings: list[PlanBinding] = []
    errors: list[PlanError] = []

    for index, declaration in enumerate(config.sensor_models):
        plan_id = f"sensor_models[{index}]"

        sensor_type_binding = _find_binding(
            existing_bindings,
            "sensor_types",
            declaration.sensor_type,
        )

        if sensor_type_binding is None:
            errors.append(
                PlanError(
                    code=PlanErrorCode.INVALID_REFERENCE,
                    resource_type="sensor_model",
                    source_path=f"{plan_id}.sensor_type",
                    message=(
                        "unable to resolve sensor type "
                        f"{declaration.sensor_type!r}"
                    ),
                )
            )
            continue

        requested_sensor_type = sensor_type_binding.resource

        rows = metadata.find_sensor_models(
            manufacturer=declaration.manufacturer,
            model=declaration.model,
        )

        if len(rows) > 1:
            errors.append(
                PlanError(
                    code=PlanErrorCode.AMBIGUOUS,
                    resource_type="sensor_model",
                    source_path=plan_id,
                    message=(
                        "sensor model natural identity matched "
                        "multiple resources"
                    ),
                    candidate_ids=tuple(
                        row.database_id for row in rows
                    ),
                )
            )
            continue

        if not rows:
            values = ResolvedSensorModelValues(
                model=declaration.model,
                manufacturer=declaration.manufacturer,
                sensor_type=requested_sensor_type,
            )

            item = ResolvedPlanItem(
                plan_id=plan_id,
                resource_type="sensor_model",
                action=PlanAction.CREATE,
                values=values,
                source_path=plan_id,
            )

            resource: ResourceRef = PlannedRef(
                resource_type="sensor_model",
                plan_id=plan_id,
            )

        else:
            row = rows[0]

            existing_sensor_type = ExistingRef(
                resource_type="sensor_type",
                database_id=row.values["sensor_type_id"],
            )

            if requested_sensor_type != existing_sensor_type:
                errors.append(
                    _conflict(
                        plan_id,
                        "sensor_model",
                        "sensor_type",
                        existing_sensor_type,
                        requested_sensor_type,
                    )
                )

            values = ResolvedSensorModelValues(
                model=row.values["model"],
                manufacturer=row.values["manufacturer"],
                sensor_type=existing_sensor_type,
            )

            item = ResolvedPlanItem(
                plan_id=plan_id,
                resource_type="sensor_model",
                action=PlanAction.REUSE,
                database_id=row.database_id,
                values=values,
                source_path=plan_id,
            )

            resource = ExistingRef(
                resource_type="sensor_model",
                database_id=row.database_id,
            )

        items.append(item)

        if declaration.ref is not None:
            bindings.append(
                PlanBinding(
                    resource_type="sensor_models",
                    alias=declaration.ref,
                    resource=resource,
                )
            )

    return tuple(items), tuple(bindings), tuple(errors)


def resolve_sensor_reference_aliases(
    registry: AliasRegistry,
    existing_bindings: tuple[PlanBinding, ...] = (),
) -> tuple[tuple[PlanBinding, ...], tuple[PlanError, ...]]:
    """Resolve sensor reference aliases against PostgreSQL."""

    bindings: list[PlanBinding] = []
    errors: list[PlanError] = []

    for entry in registry.entries:
        if not isinstance(entry, ReferenceAlias):
            continue

        if entry.resource_type != "sensors":
            continue

        sensor_model_id: int | None = None

        if entry.selector.sensor_model is not None:
            model_binding = _find_binding(
                existing_bindings,
                "sensor_models",
                entry.selector.sensor_model,
            )

            if model_binding is None:
                errors.append(
                    PlanError(
                        code=PlanErrorCode.INVALID_REFERENCE,
                        resource_type="sensors",
                        source_path=(
                            f"{entry.source_path}.sensor_model"
                        ),
                        message=(
                            "unable to resolve sensor model "
                            f"{entry.selector.sensor_model!r}"
                        ),
                    )
                )
                continue

            if isinstance(model_binding.resource, PlannedRef):
                errors.append(
                    PlanError(
                        code=PlanErrorCode.INVALID_REFERENCE,
                        resource_type="sensors",
                        source_path=(
                            f"{entry.source_path}.sensor_model"
                        ),
                        message=(
                            "existing sensor reference cannot use "
                            "a sensor model that is planned for creation"
                        ),
                    )
                )
                continue

            sensor_model_id = model_binding.resource.database_id

        rows = metadata.find_sensors(
            serial_number=entry.selector.serial_number,
            sensor_model_id=sensor_model_id,
        )

        if not rows:
            errors.append(
                PlanError(
                    code=PlanErrorCode.NOT_FOUND,
                    resource_type="sensors",
                    source_path=entry.source_path,
                    message="sensor resource not found",
                )
            )
            continue

        if len(rows) > 1:
            errors.append(
                PlanError(
                    code=PlanErrorCode.AMBIGUOUS,
                    resource_type="sensors",
                    source_path=entry.source_path,
                    message=(
                        "sensor reference matched multiple resources"
                    ),
                    candidate_ids=tuple(
                        row.database_id for row in rows
                    ),
                )
            )
            continue

        bindings.append(
            PlanBinding(
                resource_type="sensors",
                alias=entry.alias,
                resource=ExistingRef(
                    resource_type="sensor",
                    database_id=rows[0].database_id,
                ),
            )
        )

    return tuple(bindings), tuple(errors)


def resolve_sensor_declarations(
    config: ConfigModel,
    existing_bindings: tuple[PlanBinding, ...] = (),
) -> tuple[
    tuple[ResolvedPlanItem, ...],
    tuple[PlanBinding, ...],
    tuple[PlanError, ...],
]:
    """Resolve sensor declarations against PostgreSQL."""

    items: list[ResolvedPlanItem] = []
    bindings: list[PlanBinding] = []
    errors: list[PlanError] = []

    for index, declaration in enumerate(config.sensors):
        plan_id = f"sensors[{index}]"

        model_binding = _find_binding(
            existing_bindings,
            "sensor_models",
            declaration.sensor_model,
        )

        if model_binding is None:
            errors.append(
                PlanError(
                    code=PlanErrorCode.INVALID_REFERENCE,
                    resource_type="sensor",
                    source_path=f"{plan_id}.sensor_model",
                    message=(
                        "unable to resolve sensor model "
                        f"{declaration.sensor_model!r}"
                    ),
                )
            )
            continue

        requested_model = model_binding.resource

        if isinstance(requested_model, PlannedRef):
            row = None
        else:
            rows = metadata.find_sensors(
                serial_number=declaration.serial_number,
                sensor_model_id=requested_model.database_id,
            )

            if len(rows) > 1:
                errors.append(
                    PlanError(
                        code=PlanErrorCode.AMBIGUOUS,
                        resource_type="sensor",
                        source_path=plan_id,
                        message=(
                            "sensor natural identity matched "
                            "multiple resources"
                        ),
                        candidate_ids=tuple(
                            row.database_id for row in rows
                        ),
                    )
                )
                continue

            row = rows[0] if rows else None

        if row is None:
            values = ResolvedSensorValues(
                serial_number=declaration.serial_number,
                sensor_model=requested_model,
                description=declaration.description,
            )

            item = ResolvedPlanItem(
                plan_id=plan_id,
                resource_type="sensor",
                action=PlanAction.CREATE,
                values=values,
                source_path=plan_id,
            )

            resource: ResourceRef = PlannedRef(
                resource_type="sensor",
                plan_id=plan_id,
            )

        else:
            errors.extend(
                _compare_explicit_fields(
                    declaration,
                    row,
                    ("description",),
                    plan_id,
                    "sensor",
                )
            )

            existing_model = ExistingRef(
                resource_type="sensor_model",
                database_id=row.values["sensor_model_id"],
            )

            values = ResolvedSensorValues(
                serial_number=row.values["serial_number"],
                sensor_model=existing_model,
                description=row.values["description"],
            )

            item = ResolvedPlanItem(
                plan_id=plan_id,
                resource_type="sensor",
                action=PlanAction.REUSE,
                database_id=row.database_id,
                values=values,
                source_path=plan_id,
            )

            resource = ExistingRef(
                resource_type="sensor",
                database_id=row.database_id,
            )

        items.append(item)

        if declaration.ref is not None:
            bindings.append(
                PlanBinding(
                    resource_type="sensors",
                    alias=declaration.ref,
                    resource=resource,
                )
            )

    return tuple(items), tuple(bindings), tuple(errors)


# Metadata resolutions for locations


def resolve_location_reference_aliases(
    registry: AliasRegistry,
    existing_bindings: tuple[PlanBinding, ...] = (),
) -> tuple[tuple[PlanBinding, ...], tuple[PlanError, ...]]:
    """Resolve location reference aliases against PostgreSQL."""

    bindings: list[PlanBinding] = []
    errors: list[PlanError] = []

    for entry in registry.entries:
        if not isinstance(entry, ReferenceAlias):
            continue

        if entry.resource_type != "locations":
            continue

        site_id: int | None = None

        if entry.selector.site is not None:
            site_binding = _find_binding(
                existing_bindings,
                "sites",
                entry.selector.site,
            )

            if site_binding is None:
                errors.append(
                    PlanError(
                        code=PlanErrorCode.INVALID_REFERENCE,
                        resource_type="locations",
                        source_path=f"{entry.source_path}.site",
                        message=(
                            "unable to resolve site "
                            f"{entry.selector.site!r}"
                        ),
                    )
                )
                continue

            if isinstance(site_binding.resource, PlannedRef):
                errors.append(
                    PlanError(
                        code=PlanErrorCode.INVALID_REFERENCE,
                        resource_type="locations",
                        source_path=f"{entry.source_path}.site",
                        message=(
                            "existing location reference cannot use "
                            "a site that is planned for creation"
                        ),
                    )
                )
                continue

            site_id = site_binding.resource.database_id

        rows = metadata.find_locations(
            site_id=site_id,
            initial_label=entry.selector.initial_label,
        )

        if not rows:
            errors.append(
                PlanError(
                    code=PlanErrorCode.NOT_FOUND,
                    resource_type="locations",
                    source_path=entry.source_path,
                    message="location resource not found",
                )
            )
            continue

        if len(rows) > 1:
            errors.append(
                PlanError(
                    code=PlanErrorCode.AMBIGUOUS,
                    resource_type="locations",
                    source_path=entry.source_path,
                    message=(
                        "location reference matched multiple resources"
                    ),
                    candidate_ids=tuple(
                        row.database_id for row in rows
                    ),
                )
            )
            continue

        bindings.append(
            PlanBinding(
                resource_type="locations",
                alias=entry.alias,
                resource=ExistingRef(
                    resource_type="location",
                    database_id=rows[0].database_id,
                ),
            )
        )

    return tuple(bindings), tuple(errors)


def resolve_location_declarations(
    config: ConfigModel,
    existing_bindings: tuple[PlanBinding, ...] = (),
) -> tuple[
    tuple[ResolvedPlanItem, ...],
    tuple[PlanBinding, ...],
    tuple[PlanError, ...],
]:
    """Resolve location declarations against PostgreSQL."""

    items: list[ResolvedPlanItem] = []
    bindings: list[PlanBinding] = []
    errors: list[PlanError] = []

    for index, declaration in enumerate(config.locations):
        plan_id = f"locations[{index}]"

        site_binding = _find_binding(
            existing_bindings,
            "sites",
            declaration.site,
        )
        location_type_binding = _find_binding(
            existing_bindings,
            "location_types",
            declaration.location_type,
        )

        if site_binding is None:
            errors.append(
                PlanError(
                    code=PlanErrorCode.INVALID_REFERENCE,
                    resource_type="location",
                    source_path=f"{plan_id}.site",
                    message=(
                        f"unable to resolve site {declaration.site!r}"
                    ),
                )
            )

        if location_type_binding is None:
            errors.append(
                PlanError(
                    code=PlanErrorCode.INVALID_REFERENCE,
                    resource_type="location",
                    source_path=f"{plan_id}.location_type",
                    message=(
                        "unable to resolve location type "
                        f"{declaration.location_type!r}"
                    ),
                )
            )

        if site_binding is None or location_type_binding is None:
            continue

        requested_site = site_binding.resource
        requested_location_type = location_type_binding.resource

        if isinstance(requested_site, PlannedRef):
            rows = ()
        else:
            rows = metadata.find_locations(
                site_id=requested_site.database_id,
                initial_label=declaration.initial_label.label,
            )

        if len(rows) > 1:
            errors.append(
                PlanError(
                    code=PlanErrorCode.AMBIGUOUS,
                    resource_type="location",
                    source_path=plan_id,
                    message=(
                        "location natural identity matched "
                        "multiple resources"
                    ),
                    candidate_ids=tuple(
                        row.database_id for row in rows
                    ),
                )
            )
            continue

        row = rows[0] if rows else None

        if row is None:
            values = ResolvedLocationValues(
                site=requested_site,
                location_type=requested_location_type,
                latitude=declaration.latitude,
                longitude=declaration.longitude,
                height_above_ground=declaration.height_above_ground,
                azimuth=declaration.azimuth,
            )

            item = ResolvedPlanItem(
                plan_id=plan_id,
                resource_type="location",
                action=PlanAction.CREATE,
                values=values,
                source_path=plan_id,
            )

            resource: ResourceRef = PlannedRef(
                resource_type="location",
                plan_id=plan_id,
            )

        else:
            existing_location_type = ExistingRef(
                resource_type="location_type",
                database_id=row.values["location_type_id"],
            )

            if requested_location_type != existing_location_type:
                errors.append(
                    _conflict(
                        plan_id,
                        "location",
                        "location_type",
                        existing_location_type,
                        requested_location_type,
                    )
                )

            errors.extend(
                _compare_explicit_fields(
                    declaration,
                    row,
                    (
                        "latitude",
                        "longitude",
                        "height_above_ground",
                        "azimuth",
                    ),
                    plan_id,
                    "location",
                )
            )

            values = ResolvedLocationValues(
                site=ExistingRef(
                    resource_type="site",
                    database_id=row.values["site_id"],
                ),
                location_type=existing_location_type,
                latitude=row.values["latitude"],
                longitude=row.values["longitude"],
                height_above_ground=row.values[
                    "height_above_ground"
                ],
                azimuth=row.values["azimuth"],
            )

            item = ResolvedPlanItem(
                plan_id=plan_id,
                resource_type="location",
                action=PlanAction.REUSE,
                database_id=row.database_id,
                values=values,
                source_path=plan_id,
            )

            resource = ExistingRef(
                resource_type="location",
                database_id=row.database_id,
            )

        items.append(item)

        if declaration.ref is not None:
            bindings.append(
                PlanBinding(
                    resource_type="locations",
                    alias=declaration.ref,
                    resource=resource,
                )
            )

    return tuple(items), tuple(bindings), tuple(errors)


def resolve_location_label_declarations(
    config: ConfigModel,
    location_items: tuple[ResolvedPlanItem, ...],
    existing_bindings: tuple[PlanBinding, ...] = (),
) -> tuple[
    tuple[ResolvedPlanItem, ...],
    tuple[PlanError, ...],
]:
    """Resolve initial and explicit location label declarations."""

    items: list[ResolvedPlanItem] = []
    errors: list[PlanError] = []

    location_items_by_plan_id = {
        item.plan_id: item
        for item in location_items
        if item.resource_type == "location"
    }

    # Nested initial labels.
    for index, declaration in enumerate(config.locations):
        location_plan_id = f"locations[{index}]"
        label_plan_id = f"{location_plan_id}.initial_label"

        location_item = location_items_by_plan_id.get(
            location_plan_id
        )

        # Location resolution already failed.
        if location_item is None:
            continue

        if location_item.action == PlanAction.CREATE:
            location_ref: ResourceRef = PlannedRef(
                resource_type="location",
                plan_id=location_item.plan_id,
            )

            values = ResolvedLocationLabelValues(
                location=location_ref,
                label=declaration.initial_label.label,
                valid_from=declaration.initial_label.valid_from,
                valid_to=declaration.initial_label.valid_to,
            )

            items.append(
                ResolvedPlanItem(
                    plan_id=label_plan_id,
                    resource_type="location_label",
                    action=PlanAction.CREATE,
                    values=values,
                    source_path=label_plan_id,
                )
            )
            continue

        assert location_item.database_id is not None

        location_ref = ExistingRef(
            resource_type="location",
            database_id=location_item.database_id,
        )

        rows = metadata.find_location_labels(
            location_item.database_id
        )

        if not rows:
            errors.append(
                PlanError(
                    code=PlanErrorCode.NOT_FOUND,
                    resource_type="location_label",
                    source_path=label_plan_id,
                    message=(
                        "existing location has no initial label"
                    ),
                )
            )
            continue

        # D3g1 guarantees chronological ordering.
        row = rows[0]

        errors.extend(
            _compare_explicit_fields(
                declaration.initial_label,
                row,
                (
                    "label",
                    "valid_from",
                    "valid_to",
                ),
                label_plan_id,
                "location_label",
            )
        )

        values = ResolvedLocationLabelValues(
            location=location_ref,
            label=row.values["label"],
            valid_from=row.values["valid_from"],
            valid_to=row.values["valid_to"],
        )

        items.append(
            ResolvedPlanItem(
                plan_id=label_plan_id,
                resource_type="location_label",
                action=PlanAction.REUSE,
                database_id=row.database_id,
                values=values,
                source_path=label_plan_id,
            )
        )

    # Explicit top-level location_labels come next.
    
        # Explicit top-level location labels.
    for index, declaration in enumerate(config.location_labels):
        plan_id = f"location_labels[{index}]"

        location_binding = _find_binding(
            existing_bindings,
            "locations",
            declaration.location,
        )

        if location_binding is None:
            errors.append(
                PlanError(
                    code=PlanErrorCode.INVALID_REFERENCE,
                    resource_type="location_label",
                    source_path=f"{plan_id}.location",
                    message=(
                        "unable to resolve location "
                        f"{declaration.location!r}"
                    ),
                )
            )
            continue

        location_ref = location_binding.resource

        # First protect against overlap with labels already planned
        # by this configuration, including nested initial labels.
        planned_overlap = next(
            (
                item
                for item in items
                if (
                    item.resource_type == "location_label"
                    and isinstance(
                        item.values,
                        ResolvedLocationLabelValues,
                    )
                    and item.values.location == location_ref
                    and item.action == PlanAction.CREATE
                    and _intervals_overlap(
                        declaration.valid_from,
                        declaration.valid_to,
                        item.values.valid_from,
                        item.values.valid_to,
                    )
                )
            ),
            None,
        )

        if planned_overlap is not None:
            errors.append(
                PlanError(
                    code=PlanErrorCode.CONFLICT,
                    resource_type="location_label",
                    source_path=plan_id,
                    message=(
                        "location label validity overlaps "
                        f"{planned_overlap.source_path}"
                    ),
                )
            )
            continue

        # A planned location cannot have persisted label history.
        if isinstance(location_ref, PlannedRef):
            items.append(
                ResolvedPlanItem(
                    plan_id=plan_id,
                    resource_type="location_label",
                    action=PlanAction.CREATE,
                    values=ResolvedLocationLabelValues(
                        location=location_ref,
                        label=declaration.label,
                        valid_from=declaration.valid_from,
                        valid_to=declaration.valid_to,
                    ),
                    source_path=plan_id,
                )
            )
            continue

        rows = metadata.find_location_labels(
            location_ref.database_id
        )

        same_start = next(
            (
                row
                for row in rows
                if row.values["valid_from"]
                == declaration.valid_from
            ),
            None,
        )

        if same_start is not None:
            if declaration.label != same_start.values["label"]:
                errors.append(
                    _conflict(
                        plan_id,
                        "location_label",
                        "label",
                        same_start.values["label"],
                        declaration.label,
                    )
                )

            errors.extend(
                _compare_explicit_fields(
                    declaration,
                    same_start,
                    ("valid_to",),
                    plan_id,
                    "location_label",
                )
            )

            items.append(
                ResolvedPlanItem(
                    plan_id=plan_id,
                    resource_type="location_label",
                    action=PlanAction.REUSE,
                    database_id=same_start.database_id,
                    values=ResolvedLocationLabelValues(
                        location=location_ref,
                        label=same_start.values["label"],
                        valid_from=same_start.values[
                            "valid_from"
                        ],
                        valid_to=same_start.values["valid_to"],
                    ),
                    source_path=plan_id,
                )
            )
            continue

        overlapping_row = next(
            (
                row
                for row in rows
                if _intervals_overlap(
                    declaration.valid_from,
                    declaration.valid_to,
                    row.values["valid_from"],
                    row.values["valid_to"],
                )
            ),
            None,
        )

        if overlapping_row is not None:
            errors.append(
                PlanError(
                    code=PlanErrorCode.CONFLICT,
                    resource_type="location_label",
                    source_path=plan_id,
                    message=(
                        "location label validity overlaps "
                        "existing location label "
                        f"{overlapping_row.database_id}"
                    ),
                )
            )
            continue

        items.append(
            ResolvedPlanItem(
                plan_id=plan_id,
                resource_type="location_label",
                action=PlanAction.CREATE,
                values=ResolvedLocationLabelValues(
                    location=location_ref,
                    label=declaration.label,
                    valid_from=declaration.valid_from,
                    valid_to=declaration.valid_to,
                ),
                source_path=plan_id,
            )
        )

    return tuple(items), tuple(errors)

def _intervals_overlap(
    first_start: datetime,
    first_end: datetime | None,
    second_start: datetime,
    second_end: datetime | None,
) -> bool:
    """Return whether two half-open time intervals overlap."""

    return (
        first_end is None or second_start < first_end
    ) and (
        second_end is None or first_start < second_end
    )

