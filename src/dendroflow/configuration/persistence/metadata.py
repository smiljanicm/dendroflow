from ..plan import (
    PlanAction,
    ResolvedDeploymentValues,
    ResolvedLocationLabelValues,
    ResolvedLocationTypeValues,
    ResolvedLocationValues,
    ResolvedPlanItem,
    ResolvedSensorModelValues,
    ResolvedSensorTypeValues,
    ResolvedSensorValues,
    ResolvedSiteValues,
    ResolvedVariableValues,
)
from .context import ApplyContext
from .models import ApplyItemResult

_METADATA_RESOURCE_TYPES = frozenset(
    {
        "site",
        "location_type",
        "sensor_type",
        "variable",
        "sensor_model",
        "sensor",
        "location",
        "location_label",
        "deployment",
    }
)


def _create_site(
    connection: object,
    item: ResolvedPlanItem,
    context: ApplyContext,
) -> ApplyItemResult:
    if not isinstance(item.values, ResolvedSiteValues):
        raise TypeError(
            "site CREATE requires ResolvedSiteValues"
        )

    values = item.values

    parent_id = (
        None
        if values.parent is None
        else context.resolve(values.parent)
    )

    row = connection.execute(
        """
        INSERT INTO sites (
            name,
            site_code,
            description,
            latitude,
            longitude,
            parent_id
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING site_id
        """,
        (
            values.name,
            values.site_code,
            values.description,
            values.latitude,
            values.longitude,
            parent_id,
        ),
    ).fetchone()

    database_id = _returned_database_id(row)

    result = ApplyItemResult(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        action=item.action,
        database_id=database_id,
    )

    context.register(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        database_id=database_id,
    )

    return result

def create_metadata_item(
    connection: object,
    item: ResolvedPlanItem,
    context: ApplyContext,
) -> ApplyItemResult:
    """Persist one resolved METADATA CREATE item."""

    if item.action != PlanAction.CREATE:
        raise ValueError(
            "METADATA create persistence requires CREATE action"
        )

    if item.resource_type not in _METADATA_RESOURCE_TYPES:
        raise ValueError(
            "unsupported METADATA resource type: "
            f"{item.resource_type}"
        )

    if item.resource_type == "site":
        return _create_site(
            connection,
            item,
            context,
        )

    if item.resource_type == "location_type":
        return _create_location_type(
            connection,
            item,
            context,
        )

    if item.resource_type == "sensor_type":
        return _create_sensor_type(
            connection,
            item,
            context,
        )

    if item.resource_type == "variable":
        return _create_variable(
            connection,
            item,
            context,
        )

    if item.resource_type == "sensor_model":
        return _create_sensor_model(
            connection,
            item,
            context,
        )

    if item.resource_type == "sensor":
        return _create_sensor(
            connection,
            item,
            context,
        )

    if item.resource_type == "location":
        return _create_location(
            connection,
            item,
            context,
        )

    if item.resource_type == "location_label":
        return _create_location_label(
            connection,
            item,
            context,
        )

    if item.resource_type == "deployment":
        return _create_deployment(
            connection,
            item,
            context,
        )

    raise NotImplementedError(
        "METADATA CREATE writer not implemented for "
        f"{item.resource_type}"
    )


def _create_location_type(
    connection: object,
    item: ResolvedPlanItem,
    context: ApplyContext,
) -> ApplyItemResult:
    if not isinstance(
        item.values,
        ResolvedLocationTypeValues,
    ):
        raise TypeError(
            "location_type CREATE requires "
            "ResolvedLocationTypeValues"
        )

    row = connection.execute(
        """
        INSERT INTO location_types (type, description)
        VALUES (%s, %s)
        RETURNING location_type_id
        """,
        (
            item.values.type,
            item.values.description,
        ),
    ).fetchone()

    database_id = _returned_database_id(row)

    result = ApplyItemResult(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        action=item.action,
        database_id=database_id,
    )

    context.register(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        database_id=database_id,
    )

    return result


def _create_sensor_type(
    connection: object,
    item: ResolvedPlanItem,
    context: ApplyContext,
) -> ApplyItemResult:
    if not isinstance(
        item.values,
        ResolvedSensorTypeValues,
    ):
        raise TypeError(
            "sensor_type CREATE requires "
            "ResolvedSensorTypeValues"
        )

    row = connection.execute(
        """
        INSERT INTO sensor_types (type, description)
        VALUES (%s, %s)
        RETURNING sensor_type_id
        """,
        (
            item.values.type,
            item.values.description,
        ),
    ).fetchone()

    database_id = _returned_database_id(row)

    result = ApplyItemResult(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        action=item.action,
        database_id=database_id,
    )

    context.register(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        database_id=database_id,
    )

    return result


def _create_variable(
    connection: object,
    item: ResolvedPlanItem,
    context: ApplyContext,
) -> ApplyItemResult:
    if not isinstance(
        item.values,
        ResolvedVariableValues,
    ):
        raise TypeError(
            "variable CREATE requires "
            "ResolvedVariableValues"
        )

    row = connection.execute(
        """
        INSERT INTO variables (
            variable,
            derived,
            description
        )
        VALUES (%s, %s, %s)
        RETURNING variable_id
        """,
        (
            item.values.variable,
            item.values.derived,
            item.values.description,
        ),
    ).fetchone()

    database_id = _returned_database_id(row)

    result = ApplyItemResult(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        action=item.action,
        database_id=database_id,
    )

    context.register(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        database_id=database_id,
    )

    return result


def _create_sensor_model(
    connection: object,
    item: ResolvedPlanItem,
    context: ApplyContext,
) -> ApplyItemResult:
    if not isinstance(
        item.values,
        ResolvedSensorModelValues,
    ):
        raise TypeError(
            "sensor_model CREATE requires "
            "ResolvedSensorModelValues"
        )

    sensor_type_id = context.resolve(
        item.values.sensor_type
    )

    row = connection.execute(
        """
        INSERT INTO sensor_models (
            model,
            manufacturer,
            sensor_type_id
        )
        VALUES (%s, %s, %s)
        RETURNING sensor_model_id
        """,
        (
            item.values.model,
            item.values.manufacturer,
            sensor_type_id,
        ),
    ).fetchone()

    database_id = _returned_database_id(row)

    result = ApplyItemResult(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        action=item.action,
        database_id=database_id,
    )

    context.register(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        database_id=database_id,
    )

    return result


def _create_sensor(
    connection: object,
    item: ResolvedPlanItem,
    context: ApplyContext,
) -> ApplyItemResult:
    if not isinstance(
        item.values,
        ResolvedSensorValues,
    ):
        raise TypeError(
            "sensor CREATE requires ResolvedSensorValues"
        )

    sensor_model_id = context.resolve(
        item.values.sensor_model
    )

    row = connection.execute(
        """
        INSERT INTO sensors (
            sensor_model_id,
            serial_number,
            description
        )
        VALUES (%s, %s, %s)
        RETURNING sensor_id
        """,
        (
            sensor_model_id,
            item.values.serial_number,
            item.values.description,
        ),
    ).fetchone()

    database_id = _returned_database_id(row)

    result = ApplyItemResult(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        action=item.action,
        database_id=database_id,
    )

    context.register(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        database_id=database_id,
    )

    return result


def _create_location(
    connection: object,
    item: ResolvedPlanItem,
    context: ApplyContext,
) -> ApplyItemResult:
    if not isinstance(
        item.values,
        ResolvedLocationValues,
    ):
        raise TypeError(
            "location CREATE requires ResolvedLocationValues"
        )

    site_id = context.resolve(
        item.values.site
    )
    location_type_id = context.resolve(
        item.values.location_type
    )

    row = connection.execute(
        """
        INSERT INTO locations (
            site_id,
            location_type_id,
            latitude,
            longitude,
            height_above_ground,
            azimuth
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING location_id
        """,
        (
            site_id,
            location_type_id,
            item.values.latitude,
            item.values.longitude,
            item.values.height_above_ground,
            item.values.azimuth,
        ),
    ).fetchone()

    database_id = _returned_database_id(row)

    result = ApplyItemResult(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        action=item.action,
        database_id=database_id,
    )

    context.register(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        database_id=database_id,
    )

    return result


def _create_location_label(
    connection: object,
    item: ResolvedPlanItem,
    context: ApplyContext,
) -> ApplyItemResult:
    if not isinstance(
        item.values,
        ResolvedLocationLabelValues,
    ):
        raise TypeError(
            "location_label CREATE requires "
            "ResolvedLocationLabelValues"
        )

    location_id = context.resolve(
        item.values.location
    )

    row = connection.execute(
        """
        INSERT INTO location_labels (
            location_id,
            label,
            valid_from,
            valid_to
        )
        VALUES (%s, %s, %s, %s)
        RETURNING location_label_id
        """,
        (
            location_id,
            item.values.label,
            item.values.valid_from,
            item.values.valid_to,
        ),
    ).fetchone()

    database_id = _returned_database_id(row)

    result = ApplyItemResult(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        action=item.action,
        database_id=database_id,
    )

    context.register(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        database_id=database_id,
    )

    return result


def _create_deployment(
    connection: object,
    item: ResolvedPlanItem,
    context: ApplyContext,
) -> ApplyItemResult:
    if not isinstance(
        item.values,
        ResolvedDeploymentValues,
    ):
        raise TypeError(
            "deployment CREATE requires "
            "ResolvedDeploymentValues"
        )

    sensor_id = context.resolve(
        item.values.sensor
    )
    location_id = context.resolve(
        item.values.location
    )
    variable_id = context.resolve(
        item.values.variable
    )

    row = connection.execute(
        """
        INSERT INTO deployments (
            sensor_id,
            location_id,
            variable_id,
            valid_from,
            valid_to
        )
        VALUES (%s, %s, %s, %s, %s)
        RETURNING deployment_id
        """,
        (
            sensor_id,
            location_id,
            variable_id,
            item.values.valid_from,
            item.values.valid_to,
        ),
    ).fetchone()

    database_id = _returned_database_id(row)

    result = ApplyItemResult(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        action=item.action,
        database_id=database_id,
    )

    context.register(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        database_id=database_id,
    )

    return result


def _returned_database_id(row: object) -> int:
    if row is None or len(row) < 1:
        raise ValueError(
            "missing returned database id"
        )

    database_id = row[0]

    if not isinstance(database_id, int):
        raise TypeError(
            "returned database id must be an integer"
        )

    if database_id <= 0:
        raise ValueError(
            "database_id must be positive"
        )

    return database_id

