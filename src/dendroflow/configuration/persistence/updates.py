from psycopg import sql

from ..plan import (
    PlanAction,
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
from .models import ApplyError, ApplyErrorCode, ApplyItemResult

_SITE_UPDATE_COLUMNS = {
    "name": "name",
    "site_code": "site_code",
    "description": "description",
    "latitude": "latitude",
    "longitude": "longitude",
    "parent": "parent_id",
}

_LOCATION_TYPE_UPDATE_COLUMNS = {
    "type": "type",
    "description": "description",
}

_SENSOR_TYPE_UPDATE_COLUMNS = {
    "type": "type",
    "description": "description",
}

_VARIABLE_UPDATE_COLUMNS = {
    "variable": "variable",
    "derived": "derived",
    "description": "description",
}

_SIMPLE_UPDATE_SPECS = {
    "location_type": (
        ResolvedLocationTypeValues,
        "location_types",
        "location_type_id",
        _LOCATION_TYPE_UPDATE_COLUMNS,
    ),
    "sensor_type": (
        ResolvedSensorTypeValues,
        "sensor_types",
        "sensor_type_id",
        _SENSOR_TYPE_UPDATE_COLUMNS,
    ),
    "variable": (
        ResolvedVariableValues,
        "variables",
        "variable_id",
        _VARIABLE_UPDATE_COLUMNS,
    ),
}

_SENSOR_MODEL_UPDATE_COLUMNS = {
    "manufacturer": "manufacturer",
    "model": "model",
    "sensor_type": "sensor_type_id",
}

_SENSOR_UPDATE_COLUMNS = {
    "serial_number": "serial_number",
    "description": "description",
    "sensor_model": "sensor_model_id",
}

_LOCATION_UPDATE_COLUMNS = {
    "site": "site_id",
    "location_type": "location_type_id",
    "latitude": "latitude",
    "longitude": "longitude",
    "height_above_ground": "height_above_ground",
    "azimuth": "azimuth",
}

def _validate_site_update(
    item: ResolvedPlanItem,
) -> ResolvedSiteValues:
    """Validate a site UPDATE before database access."""

    if item.action != PlanAction.UPDATE:
        raise ValueError(
            "METADATA update persistence requires UPDATE action"
        )

    if item.resource_type != "site":
        raise ValueError(
            "unsupported METADATA update resource type: "
            f"{item.resource_type}"
        )

    if not isinstance(item.values, ResolvedSiteValues):
        raise TypeError(
            "site UPDATE requires ResolvedSiteValues"
        )

    if (
        type(item.database_id) is not int
        or item.database_id <= 0
    ):
        raise ValueError(
            "site UPDATE requires a positive integer database_id"
        )

    if not item.changes:
        raise ValueError(
            "site UPDATE requires at least one change"
        )

    seen_fields: set[str] = set()

    for change in item.changes:
        if change.field not in _SITE_UPDATE_COLUMNS:
            raise ValueError(
                f"unsupported site UPDATE field: {change.field}"
            )

        if change.field in seen_fields:
            raise ValueError(
                f"duplicate site UPDATE field: {change.field}"
            )

        seen_fields.add(change.field)

        if change.after != getattr(item.values, change.field):
            raise ValueError(
                "site UPDATE change.after does not match "
                f"resolved values: {change.field}"
            )

    return item.values


def _validate_metadata_update(
    item: ResolvedPlanItem,
    *,
    values_type: type,
    columns: dict[str, str],
) -> object:
    """Validate a METADATA UPDATE before database access."""

    resource_type = item.resource_type

    if item.action != PlanAction.UPDATE:
        raise ValueError(
            "METADATA update persistence requires UPDATE action"
        )

    if not isinstance(item.values, values_type):
        raise TypeError(
            f"{resource_type} UPDATE requires {values_type.__name__}"
        )

    if (
        type(item.database_id) is not int
        or item.database_id <= 0
    ):
        raise ValueError(
            f"{resource_type} UPDATE requires "
            "a positive integer database_id"
        )

    if not item.changes:
        raise ValueError(
            f"{resource_type} UPDATE requires at least one change"
        )

    seen_fields: set[str] = set()

    for change in item.changes:
        if change.field not in columns:
            raise ValueError(
                f"unsupported {resource_type} UPDATE field: "
                f"{change.field}"
            )

        if change.field in seen_fields:
            raise ValueError(
                f"duplicate {resource_type} UPDATE field: "
                f"{change.field}"
            )

        seen_fields.add(change.field)

        if change.after != getattr(item.values, change.field):
            raise ValueError(
                f"{resource_type} UPDATE change.after does not match "
                f"resolved values: {change.field}"
            )

    return item.values


def _execute_metadata_update(
    connection: object,
    item: ResolvedPlanItem,
    *,
    table: str,
    primary_key: str,
    updates: tuple[tuple[str, object, object], ...],
) -> ApplyItemResult:
    """Execute a validated UPDATE.

    Each update contains:
    (database column, final value, previous value).

    Table and column names must come from writer-owned mappings.
    """

    if not updates:
        raise ValueError(
            "METADATA UPDATE requires at least one column"
        )

    assignments = []
    guards = []
    new_values = []
    old_values = []

    for column_name, after, before in updates:
        column = sql.Identifier(column_name)

        assignments.append(
            sql.SQL("{} = %s").format(column)
        )
        guards.append(
            sql.SQL("{} IS NOT DISTINCT FROM %s").format(column)
        )
        new_values.append(after)
        old_values.append(before)

    query = sql.SQL(
        """
        UPDATE {table}
        SET {assignments}
        WHERE {primary_key} = %s
          AND {guards}
        RETURNING {primary_key}
        """
    ).format(
        table=sql.Identifier(table),
        primary_key=sql.Identifier(primary_key),
        assignments=sql.SQL(", ").join(assignments),
        guards=sql.SQL(" AND ").join(guards),
    )

    params = (
        *new_values,
        item.database_id,
        *old_values,
    )

    row = connection.execute(query, params).fetchone()

    if row is None:
        raise ApplyError(
            ApplyErrorCode.STALE_PLAN,
            (
                f"{item.resource_type} UPDATE plan is stale: "
                f"{item.plan_id} "
                f"({primary_key}={item.database_id})"
            ),
        )

    if (
        len(row) != 1
        or type(row[0]) is not int
        or row[0] != item.database_id
    ):
        raise ValueError(
            f"{item.resource_type} UPDATE returned "
            "an unexpected database_id"
        )

    return ApplyItemResult(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        action=item.action,
        database_id=item.database_id,
    )


def update_metadata_item(
    connection: object,
    item: ResolvedPlanItem,
    context: ApplyContext,
) -> ApplyItemResult:
    """Persist one resolved METADATA UPDATE item."""

    if item.resource_type == "location":
        values = _validate_metadata_update(
            item,
            values_type=ResolvedLocationValues,
            columns=_LOCATION_UPDATE_COLUMNS,
        )

        updates = []

        for change in item.changes:
            after = getattr(values, change.field)
            before = change.before

            if change.field in {"site", "location_type"}:
                after = context.resolve(after)
                before = context.resolve(before)

            updates.append(
                (
                    _LOCATION_UPDATE_COLUMNS[change.field],
                    after,
                    before,
                )
            )

        return _execute_metadata_update(
            connection,
            item,
            table="locations",
            primary_key="location_id",
            updates=tuple(updates),
        )

    if item.resource_type == "sensor":
        values = _validate_metadata_update(
            item,
            values_type=ResolvedSensorValues,
            columns=_SENSOR_UPDATE_COLUMNS,
        )

        updates = []

        for change in item.changes:
            after = getattr(values, change.field)
            before = change.before

            if change.field == "sensor_model":
                after = context.resolve(after)
                before = context.resolve(before)

            updates.append(
                (
                    _SENSOR_UPDATE_COLUMNS[change.field],
                    after,
                    before,
                )
            )

        return _execute_metadata_update(
            connection,
            item,
            table="sensors",
            primary_key="sensor_id",
            updates=tuple(updates),
        )
    
    if item.resource_type == "sensor_model":
        values = _validate_metadata_update(
            item,
            values_type=ResolvedSensorModelValues,
            columns=_SENSOR_MODEL_UPDATE_COLUMNS,
        )

        updates = []

        for change in item.changes:
            after = getattr(values, change.field)
            before = change.before

            if change.field == "sensor_type":
                after = context.resolve(after)
                before = context.resolve(before)

            updates.append(
                (
                    _SENSOR_MODEL_UPDATE_COLUMNS[change.field],
                    after,
                    before,
                )
            )

        return _execute_metadata_update(
            connection,
            item,
            table="sensor_models",
            primary_key="sensor_model_id",
            updates=tuple(updates),
        )
    
    if item.resource_type in _SIMPLE_UPDATE_SPECS:
        values_type, table, primary_key, columns = (
            _SIMPLE_UPDATE_SPECS[item.resource_type]
        )

        values = _validate_metadata_update(
            item,
            values_type=values_type,
            columns=columns,
        )

        updates = tuple(
            (
                columns[change.field],
                getattr(values, change.field),
                change.before,
            )
            for change in item.changes
        )

        return _execute_metadata_update(
            connection,
            item,
            table=table,
            primary_key=primary_key,
            updates=updates,
        )
    
    values = _validate_site_update(item)

    updates: list[tuple[str, object, object]] = []

    for change in item.changes:
        after = getattr(values, change.field)
        before = change.before

        if change.field == "parent":
            after = (
                None if after is None else context.resolve(after)
            )
            before = (
                None if before is None else context.resolve(before)
            )

        updates.append(
            (
                _SITE_UPDATE_COLUMNS[change.field],
                after,
                before,
            )
        )

    return _execute_metadata_update(
        connection,
        item,
        table="sites",
        primary_key="site_id",
        updates=tuple(updates),
    )

