from ..plan import (
    PlanAction,
    ResolvedLocationTypeValues,
    ResolvedPlanItem,
    ResolvedSensorTypeValues,
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

    row = connection.execute(
        """
        INSERT INTO sites (name, site_code)
        VALUES (%s, %s)
        RETURNING site_id
        """,
        (
            item.values.name,
            item.values.site_code,
        ),
    ).fetchone()

    database_id = row[0]

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

    database_id = row[0]

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

    database_id = row[0]

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

    database_id = row[0]

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

