from psycopg import sql

from ..plan import PlanAction, ResolvedPlanItem, ResolvedSiteValues
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


def update_metadata_item(
    connection: object,
    item: ResolvedPlanItem,
    context: ApplyContext,
) -> ApplyItemResult:
    """Persist one resolved METADATA UPDATE item."""

    values = _validate_site_update(item)

    assignments = []
    guards = []
    new_values = []
    old_values = []

    for change in item.changes:
        column = sql.Identifier(
            _SITE_UPDATE_COLUMNS[change.field]
        )

        after = getattr(values, change.field)
        before = change.before

        if change.field == "parent":
            after = (
                None if after is None else context.resolve(after)
            )
            before = (
                None if before is None else context.resolve(before)
            )

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
        UPDATE sites
        SET {assignments}
        WHERE site_id = %s
          AND {guards}
        RETURNING site_id
        """
    ).format(
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
                f"site UPDATE plan is stale: {item.plan_id} "
                f"(site_id={item.database_id})"
            ),
        )

    if (
        len(row) != 1
        or type(row[0]) is not int
        or row[0] != item.database_id
    ):
        raise ValueError(
            "site UPDATE returned an unexpected database_id"
        )

    return ApplyItemResult(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        action=item.action,
        database_id=item.database_id,
    )

