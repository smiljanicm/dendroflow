from ..models import ConfigModel
from ..plan import (
    ExistingRef,
    FieldChange,
    PlanAction,
    PlanBinding,
    PlanError,
    PlanErrorCode,
    ResolvedDeploymentValues,
    ResolvedLocationTypeValues,
    ResolvedPlanItem,
    ResolvedSensorTypeValues,
    ResolvedSensorValues,
    ResolvedSiteValues,
    ResolvedVariableValues,
    ResourceRef,
)
from .common import _find_binding
from .selectors import (
    resolve_deployment_selector,
    resolve_location_type_selector,
    resolve_sensor_selector,
    resolve_sensor_type_selector,
    resolve_site_selector,
    resolve_variable_selector,
)


def resolve_sensor_updates(
    config: ConfigModel,
    existing_bindings: tuple[PlanBinding, ...] = (),
) -> tuple[
    tuple[ResolvedPlanItem, ...],
    tuple[PlanError, ...],
]:
    """Resolve explicit sensor updates."""

    items: list[ResolvedPlanItem] = []
    errors: list[PlanError] = []

    for index, update_config in enumerate(
        config.updates.sensors
    ):
        source_path = f"updates.sensors[{index}]"

        row, selector_errors = resolve_sensor_selector(
            update_config.update,
            source_path=f"{source_path}.update",
            existing_bindings=existing_bindings,
        )

        if selector_errors:
            errors.extend(selector_errors)
            continue

        assert row is not None

        changes: list[FieldChange] = []

        serial_number = row.values["serial_number"]
        description = row.values["description"]

        fields_set = update_config.set.model_fields_set

        if "serial_number" in fields_set:
            requested_serial_number = (
                update_config.set.serial_number
            )

            if requested_serial_number != serial_number:
                changes.append(
                    FieldChange(
                        field="serial_number",
                        before=serial_number,
                        after=requested_serial_number,
                        identity_change=True,
                    )
                )
                serial_number = requested_serial_number

        if "description" in fields_set:
            requested_description = (
                update_config.set.description
            )

            if requested_description != description:
                changes.append(
                    FieldChange(
                        field="description",
                        before=description,
                        after=requested_description,
                        identity_change=False,
                    )
                )
                description = requested_description

        if not changes:
            continue

        sensor_model_id = row.values["sensor_model_id"]

        items.append(
            ResolvedPlanItem(
                plan_id=source_path,
                resource_type="sensor",
                action=PlanAction.UPDATE,
                database_id=row.database_id,
                values=ResolvedSensorValues(
                    serial_number=serial_number,
                    sensor_model=ExistingRef(
                        resource_type="sensor_model",
                        database_id=sensor_model_id,
                    ),
                    description=description,
                ),
                changes=tuple(changes),
                source_path=source_path,
            )
        )

    return tuple(items), tuple(errors)


# Deployment updates


def _resolve_set_relationship(
    *,
    alias: str,
    resource_type: str,
    binding_type: str,
    source_path: str,
    existing_bindings: tuple[PlanBinding, ...],
) -> tuple[ResourceRef | None, PlanError | None]:
    binding = _find_binding(
        existing_bindings,
        binding_type,
        alias,
    )

    if binding is None:
        return None, PlanError(
            code=PlanErrorCode.INVALID_REFERENCE,
            resource_type="deployment",
            source_path=source_path,
            message=(
                f"unable to resolve {resource_type} "
                f"{alias!r}"
            ),
        )

    return binding.resource, None


def resolve_deployment_updates(
    config: ConfigModel,
    existing_bindings: tuple[PlanBinding, ...] = (),
) -> tuple[
    tuple[ResolvedPlanItem, ...],
    tuple[PlanError, ...],
]:
    """Resolve explicit deployment updates."""

    items: list[ResolvedPlanItem] = []
    errors: list[PlanError] = []

    for index, update_config in enumerate(
        config.updates.deployments
    ):
        source_path = (
            f"updates.deployments[{index}]"
        )

        row, selector_errors = (
            resolve_deployment_selector(
                update_config.update,
                source_path=f"{source_path}.update",
                existing_bindings=existing_bindings,
            )
        )

        if selector_errors:
            errors.extend(selector_errors)
            continue

        assert row is not None

        sensor: ResourceRef = ExistingRef(
            resource_type="sensor",
            database_id=row.values["sensor_id"],
        )
        location: ResourceRef = ExistingRef(
            resource_type="location",
            database_id=row.values["location_id"],
        )
        variable: ResourceRef = ExistingRef(
            resource_type="variable",
            database_id=row.values["variable_id"],
        )

        valid_from = row.values["valid_from"]
        valid_to = row.values["valid_to"]

        changes: list[FieldChange] = []
        update_errors: list[PlanError] = []

        fields_set = update_config.set.model_fields_set

        relationship_fields = (
            (
                "sensor",
                "sensors",
                sensor,
            ),
            (
                "location",
                "locations",
                location,
            ),
            (
                "variable",
                "variables",
                variable,
            ),
        )

        resolved_relationships: dict[
            str, ResourceRef
        ] = {
            "sensor": sensor,
            "location": location,
            "variable": variable,
        }

        for (
            field,
            binding_type,
            existing_resource,
        ) in relationship_fields:
            if field not in fields_set:
                continue

            alias = getattr(update_config.set, field)

            if alias is None:
                update_errors.append(
                    PlanError(
                        code=(
                            PlanErrorCode.INVALID_REFERENCE
                        ),
                        resource_type="deployment",
                        source_path=(
                            f"{source_path}.set.{field}"
                        ),
                        message=(
                            f"{field} cannot be null"
                        ),
                    )
                )
                continue

            requested, error = (
                _resolve_set_relationship(
                    alias=alias,
                    resource_type=field,
                    binding_type=binding_type,
                    source_path=(
                        f"{source_path}.set.{field}"
                    ),
                    existing_bindings=(
                        existing_bindings
                    ),
                )
            )

            if error is not None:
                update_errors.append(error)
                continue

            assert requested is not None

            resolved_relationships[field] = (
                requested
            )

            if requested != existing_resource:
                changes.append(
                    FieldChange(
                        field=field,
                        before=existing_resource,
                        after=requested,
                        identity_change=True,
                    )
                )

        if "valid_from" in fields_set:
            requested_valid_from = (
                update_config.set.valid_from
            )

            if requested_valid_from != valid_from:
                changes.append(
                    FieldChange(
                        field="valid_from",
                        before=valid_from,
                        after=requested_valid_from,
                        identity_change=True,
                    )
                )
                valid_from = requested_valid_from

        if "valid_to" in fields_set:
            requested_valid_to = (
                update_config.set.valid_to
            )

            if requested_valid_to != valid_to:
                changes.append(
                    FieldChange(
                        field="valid_to",
                        before=valid_to,
                        after=requested_valid_to,
                        identity_change=False,
                    )
                )
                valid_to = requested_valid_to

        if update_errors:
            errors.extend(update_errors)
            continue

        if not changes:
            continue

        items.append(
            ResolvedPlanItem(
                plan_id=source_path,
                resource_type="deployment",
                action=PlanAction.UPDATE,
                database_id=row.database_id,
                values=ResolvedDeploymentValues(
                    sensor=resolved_relationships[
                        "sensor"
                    ],
                    location=resolved_relationships[
                        "location"
                    ],
                    variable=resolved_relationships[
                        "variable"
                    ],
                    valid_from=valid_from,
                    valid_to=valid_to,
                ),
                changes=tuple(changes),
                source_path=source_path,
            )
        )

    return tuple(items), tuple(errors)


# Site Updates


def resolve_site_updates(
    config: ConfigModel,
) -> tuple[
    tuple[ResolvedPlanItem, ...],
    tuple[PlanError, ...],
]:
    """Resolve explicit site updates."""

    items: list[ResolvedPlanItem] = []
    errors: list[PlanError] = []

    for index, update_config in enumerate(
        config.updates.sites
    ):
        source_path = f"updates.sites[{index}]"

        row, selector_errors = resolve_site_selector(
            update_config.update,
            source_path=f"{source_path}.update",
        )

        if selector_errors:
            errors.extend(selector_errors)
            continue

        assert row is not None

        site_code = row.values["site_code"]
        name = row.values["name"]
        description = row.values["description"]
        latitude = row.values["latitude"]
        longitude = row.values["longitude"]
        parent_id = row.values["parent_id"]

        changes: list[FieldChange] = []
        fields_set = update_config.set.model_fields_set

        if "site_code" in fields_set:
            requested = update_config.set.site_code

            if requested != site_code:
                changes.append(
                    FieldChange(
                        field="site_code",
                        before=site_code,
                        after=requested,
                        identity_change=True,
                    )
                )
                site_code = requested

        if "name" in fields_set:
            requested = update_config.set.name

            if requested != name:
                changes.append(
                    FieldChange(
                        field="name",
                        before=name,
                        after=requested,
                        identity_change=False,
                    )
                )
                name = requested

        if "description" in fields_set:
            requested = update_config.set.description

            if requested != description:
                changes.append(
                    FieldChange(
                        field="description",
                        before=description,
                        after=requested,
                        identity_change=False,
                    )
                )
                description = requested

        if "latitude" in fields_set:
            requested = update_config.set.latitude

            if requested != latitude:
                changes.append(
                    FieldChange(
                        field="latitude",
                        before=latitude,
                        after=requested,
                        identity_change=False,
                    )
                )
                latitude = requested

        if "longitude" in fields_set:
            requested = update_config.set.longitude

            if requested != longitude:
                changes.append(
                    FieldChange(
                        field="longitude",
                        before=longitude,
                        after=requested,
                        identity_change=False,
                    )
                )
                longitude = requested

        if not changes:
            continue

        parent = (
            None
            if parent_id is None
            else ExistingRef(
                resource_type="site",
                database_id=parent_id,
            )
        )

        if (latitude is None) != (longitude is None):
            errors.append(
                PlanError(
                    code=PlanErrorCode.CONFLICT,
                    resource_type="site",
                    source_path=f"{source_path}.set",
                    message=(
                        "site latitude and longitude must either "
                        "both be set or both be null"
                    ),
                )
            )
            continue

        items.append(
            ResolvedPlanItem(
                plan_id=source_path,
                resource_type="site",
                action=PlanAction.UPDATE,
                database_id=row.database_id,
                values=ResolvedSiteValues(
                    site_code=site_code,
                    name=name,
                    description=description,
                    latitude=latitude,
                    longitude=longitude,
                    parent=parent,
                ),
                changes=tuple(changes),
                source_path=source_path,
            )
        )

    return tuple(items), tuple(errors)


def resolve_location_type_updates(
    config: ConfigModel,
) -> tuple[
    tuple[ResolvedPlanItem, ...],
    tuple[PlanError, ...],
]:
    """Resolve explicit location-type updates."""

    items: list[ResolvedPlanItem] = []
    errors: list[PlanError] = []

    for index, update_config in enumerate(
        config.updates.location_types
    ):
        source_path = f"updates.location_types[{index}]"

        row, selector_errors = resolve_location_type_selector(
            update_config.update,
            source_path=f"{source_path}.update",
        )

        if selector_errors:
            errors.extend(selector_errors)
            continue

        assert row is not None

        type_ = row.values["type"]
        description = row.values["description"]

        changes: list[FieldChange] = []
        fields_set = update_config.set.model_fields_set

        if "type" in fields_set:
            requested = update_config.set.type

            if requested != type_:
                changes.append(
                    FieldChange(
                        field="type",
                        before=type_,
                        after=requested,
                        identity_change=True,
                    )
                )
                type_ = requested

        if "description" in fields_set:
            requested = update_config.set.description

            if requested != description:
                changes.append(
                    FieldChange(
                        field="description",
                        before=description,
                        after=requested,
                        identity_change=False,
                    )
                )
                description = requested

        if not changes:
            continue

        items.append(
            ResolvedPlanItem(
                plan_id=source_path,
                resource_type="location_type",
                action=PlanAction.UPDATE,
                database_id=row.database_id,
                values=ResolvedLocationTypeValues(
                    type=type_,
                    description=description,
                ),
                changes=tuple(changes),
                source_path=source_path,
            )
        )

    return tuple(items), tuple(errors)


def resolve_sensor_type_updates(
    config: ConfigModel,
) -> tuple[
    tuple[ResolvedPlanItem, ...],
    tuple[PlanError, ...],
]:
    """Resolve explicit sensor-type updates."""

    items: list[ResolvedPlanItem] = []
    errors: list[PlanError] = []

    for index, update_config in enumerate(
        config.updates.sensor_types
    ):
        source_path = f"updates.sensor_types[{index}]"

        row, selector_errors = resolve_sensor_type_selector(
            update_config.update,
            source_path=f"{source_path}.update",
        )

        if selector_errors:
            errors.extend(selector_errors)
            continue

        assert row is not None

        type_ = row.values["type"]
        description = row.values["description"]

        changes: list[FieldChange] = []
        fields_set = update_config.set.model_fields_set

        if "type" in fields_set:
            requested = update_config.set.type

            if requested != type_:
                changes.append(
                    FieldChange(
                        field="type",
                        before=type_,
                        after=requested,
                        identity_change=True,
                    )
                )
                type_ = requested

        if "description" in fields_set:
            requested = update_config.set.description

            if requested != description:
                changes.append(
                    FieldChange(
                        field="description",
                        before=description,
                        after=requested,
                        identity_change=False,
                    )
                )
                description = requested

        if not changes:
            continue

        items.append(
            ResolvedPlanItem(
                plan_id=source_path,
                resource_type="sensor_type",
                action=PlanAction.UPDATE,
                database_id=row.database_id,
                values=ResolvedSensorTypeValues(
                    type=type_,
                    description=description,
                ),
                changes=tuple(changes),
                source_path=source_path,
            )
        )

    return tuple(items), tuple(errors)


def resolve_variable_updates(
    config: ConfigModel,
) -> tuple[
    tuple[ResolvedPlanItem, ...],
    tuple[PlanError, ...],
]:
    """Resolve explicit variable updates."""

    items: list[ResolvedPlanItem] = []
    errors: list[PlanError] = []

    for index, update_config in enumerate(
        config.updates.variables
    ):
        source_path = f"updates.variables[{index}]"

        row, selector_errors = resolve_variable_selector(
            update_config.update,
            source_path=f"{source_path}.update",
        )

        if selector_errors:
            errors.extend(selector_errors)
            continue

        assert row is not None

        variable = row.values["variable"]
        derived = row.values["derived"]
        description = row.values["description"]

        changes: list[FieldChange] = []
        fields_set = update_config.set.model_fields_set

        if "variable" in fields_set:
            requested = update_config.set.variable

            if requested != variable:
                changes.append(
                    FieldChange(
                        field="variable",
                        before=variable,
                        after=requested,
                        identity_change=True,
                    )
                )
                variable = requested

        if "derived" in fields_set:
            requested = update_config.set.derived

            if requested != derived:
                changes.append(
                    FieldChange(
                        field="derived",
                        before=derived,
                        after=requested,
                        identity_change=False,
                    )
                )
                derived = requested

        if "description" in fields_set:
            requested = update_config.set.description

            if requested != description:
                changes.append(
                    FieldChange(
                        field="description",
                        before=description,
                        after=requested,
                        identity_change=False,
                    )
                )
                description = requested

        if not changes:
            continue

        items.append(
            ResolvedPlanItem(
                plan_id=source_path,
                resource_type="variable",
                action=PlanAction.UPDATE,
                database_id=row.database_id,
                values=ResolvedVariableValues(
                    variable=variable,
                    derived=derived,
                    description=description,
                ),
                changes=tuple(changes),
                source_path=source_path,
            )
        )

    return tuple(items), tuple(errors)

