from collections.abc import Mapping

from psycopg.types.json import Jsonb

from ..plan import (
    ExistingRef,
    PlanAction,
    PlannedRef,
    ResolvedFileValues,
    ResolvedInterfaceValues,
    ResolvedPlanItem,
    ResourceRef,
)
from .context import ApplyContext
from .models import ApplyItemResult


def create_raw_item(
    connection: object,
    item: ResolvedPlanItem,
    context: ApplyContext,
) -> ApplyItemResult:
    """Persist one resolved RAW CREATE item.

    The caller owns the connection, transaction, and context lifecycle.
    A returned result does not mean the transaction has committed.
    """
    if item.action != PlanAction.CREATE:
        raise ValueError(
            "RAW create persistence requires CREATE action"
        )

    if item.resource_type == "file":
        return _create_file(connection, item, context)

    if item.resource_type == "interface":
        return _create_interface(connection, item, context)

    raise ValueError(
        "unsupported RAW CREATE resource type: "
        f"{item.resource_type}"
    )


def _create_file(
    connection: object,
    item: ResolvedPlanItem,
    context: ApplyContext,
) -> ApplyItemResult:
    if not isinstance(item.values, ResolvedFileValues):
        raise TypeError(
            "file CREATE requires ResolvedFileValues"
        )

    values = item.values

    if not isinstance(values.reader_config, Mapping):
        raise TypeError(
            "reader_config must be a mapping"
        )

    row = connection.execute(
        """
        INSERT INTO files (
            filepath,
            timestamp_timezone,
            timestamp_format,
            reader_config
        )
        VALUES (%s, %s, %s, %s)
        RETURNING file_id
        """,
        (
            values.filepath,
            values.timestamp_timezone,
            values.timestamp_format,
            Jsonb(dict(values.reader_config)),
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


def _create_interface(
    connection: object,
    item: ResolvedPlanItem,
    context: ApplyContext,
) -> ApplyItemResult:
    if not isinstance(item.values, ResolvedInterfaceValues):
        raise TypeError(
            "interface CREATE requires ResolvedInterfaceValues"
        )

    values = item.values

    file_id = _resolve_interface_reference(
        values.file,
        "file",
        context,
    )
    deployment_id = _resolve_interface_reference(
        values.deployment,
        "deployment",
        context,
    )

    row = connection.execute(
        """
        INSERT INTO sensor_file_interfaces (
            file_id,
            deployment_id,
            values_column,
            timestamp_column,
            unit
        )
        VALUES (%s, %s, %s, %s, %s)
        RETURNING interface_id
        """,
        (
            file_id,
            deployment_id,
            values.values_column,
            values.timestamp_column,
            values.unit,
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


def _resolve_interface_reference(
    reference: ResourceRef,
    expected_type: str,
    context: ApplyContext,
) -> int:
    if not isinstance(reference, (ExistingRef, PlannedRef)):
        raise TypeError(
            f"interface {expected_type} requires a resource reference"
        )

    if reference.resource_type != expected_type:
        raise ValueError(
            f"interface {expected_type} requires "
            f"resource type {expected_type}"
        )

    return context.resolve(reference)


def _returned_database_id(row: object) -> int:
    if not isinstance(row, (tuple, list)) or len(row) != 1:
        raise ValueError(
            "expected one returned database id"
        )

    database_id = row[0]

    if type(database_id) is not int:
        raise TypeError(
            "returned database id must be an integer"
        )

    if database_id <= 0:
        raise ValueError(
            "database_id must be positive"
        )

    return database_id
