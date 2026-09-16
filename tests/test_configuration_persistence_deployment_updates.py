from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from dendroflow.configuration.persistence.context import ApplyContext
from dendroflow.configuration.persistence.models import (
    ApplyError,
    ApplyErrorCode,
    ApplyItemResult,
)
from dendroflow.configuration.persistence.updates import (
    update_metadata_item,
)
from dendroflow.configuration.plan import (
    ExistingRef,
    FieldChange,
    PlanAction,
    PlannedRef,
    ResolvedDeploymentValues,
    ResolvedPlanItem,
)


class FakeUpdateConnection:
    def __init__(self, returned_row=(81,)):
        self.returned_row = returned_row
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))
        return self

    def fetchone(self):
        return self.returned_row


def _deployment_update() -> ResolvedPlanItem:
    before = datetime(
        2024,
        1,
        1,
        0,
        0,
        tzinfo=timezone.utc,
    )
    after = datetime(
        2024,
        1,
        2,
        0,
        0,
        tzinfo=timezone.utc,
    )

    return ResolvedPlanItem(
        plan_id="updates.deployments[0]",
        resource_type="deployment",
        action=PlanAction.UPDATE,
        database_id=81,
        values=ResolvedDeploymentValues(
            sensor=ExistingRef("sensor", 31),
            location=ExistingRef("location", 41),
            variable=ExistingRef("variable", 51),
            valid_from=before,
            valid_to=after,
        ),
        changes=(
            FieldChange(
                field="valid_to",
                before=None,
                after=after,
            ),
        ),
    )


@pytest.mark.parametrize(
    ("field", "before", "after"),
    [
        (
            "valid_from",
            datetime(
                2024,
                1,
                1,
                0,
                0,
                tzinfo=timezone.utc,
            ),
            datetime(
                2024,
                1,
                1,
                1,
                30,
                15,
                123456,
                tzinfo=timezone(
                    timedelta(hours=2)
                ),
            ),
        ),
        (
            "valid_to",
            None,
            datetime(
                2024,
                1,
                2,
                0,
                0,
                tzinfo=timezone.utc,
            ),
        ),
        (
            "valid_to",
            datetime(
                2024,
                1,
                2,
                0,
                0,
                tzinfo=timezone.utc,
            ),
            datetime(
                2024,
                1,
                3,
                0,
                0,
                tzinfo=timezone.utc,
            ),
        ),
        (
            "valid_to",
            datetime(
                2024,
                1,
                2,
                0,
                0,
                tzinfo=timezone.utc,
            ),
            None,
        ),
    ],
)
def test_deployment_update_persists_timestamp_change(
    field,
    before,
    after,
):
    connection = FakeUpdateConnection()
    original = _deployment_update()

    item = replace(
        original,
        values=replace(
            original.values,
            **{field: after},
        ),
        changes=(
            FieldChange(field, before, after),
        ),
    )

    result = update_metadata_item(
        connection,
        item,
        ApplyContext(),
    )

    assert result == ApplyItemResult(
        plan_id="updates.deployments[0]",
        resource_type="deployment",
        action=PlanAction.UPDATE,
        database_id=81,
    )
    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        f'UPDATE "deployments" SET "{field}" = %s '
        'WHERE "deployment_id" = %s '
        f'AND "{field}" IS NOT DISTINCT FROM %s '
        'RETURNING "deployment_id"'
    )
    assert params == (after, 81, before)


def test_deployment_update_persists_validity_interval():
    connection = FakeUpdateConnection()
    original = _deployment_update()

    old_valid_from = datetime(
        2024,
        1,
        1,
        0,
        0,
        tzinfo=timezone.utc,
    )
    old_valid_to = datetime(
        2024,
        1,
        3,
        0,
        0,
        tzinfo=timezone.utc,
    )
    new_valid_from = datetime(
        2024,
        1,
        2,
        0,
        0,
        tzinfo=timezone.utc,
    )
    new_valid_to = datetime(
        2024,
        1,
        4,
        0,
        0,
        tzinfo=timezone.utc,
    )

    item = replace(
        original,
        values=replace(
            original.values,
            valid_from=new_valid_from,
            valid_to=new_valid_to,
        ),
        changes=(
            FieldChange(
                "valid_from",
                old_valid_from,
                new_valid_from,
            ),
            FieldChange(
                "valid_to",
                old_valid_to,
                new_valid_to,
            ),
        ),
    )

    update_metadata_item(
        connection,
        item,
        ApplyContext(),
    )

    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        'UPDATE "deployments" '
        'SET "valid_from" = %s, "valid_to" = %s '
        'WHERE "deployment_id" = %s '
        'AND "valid_from" IS NOT DISTINCT FROM %s '
        'AND "valid_to" IS NOT DISTINCT FROM %s '
        'RETURNING "deployment_id"'
    )
    assert params == (
        new_valid_from,
        new_valid_to,
        81,
        old_valid_from,
        old_valid_to,
    )


@pytest.mark.parametrize(
    ("overrides", "error_type", "message"),
    [
        (
            {
                "action": PlanAction.CREATE,
                "database_id": None,
            },
            ValueError,
            "requires UPDATE action",
        ),
        (
            {
                "action": PlanAction.REUSE,
            },
            ValueError,
            "requires UPDATE action",
        ),
        (
            {
                "values": object(),
            },
            TypeError,
            "requires ResolvedDeploymentValues",
        ),
        (
            {
                "database_id": 0,
            },
            ValueError,
            "positive integer database_id",
        ),
        (
            {
                "changes": (
                    FieldChange(
                        "unknown",
                        None,
                        "value",
                    ),
                ),
            },
            ValueError,
            "unsupported deployment UPDATE field",
        ),
        (
            {
                "changes": (
                    FieldChange(
                        "valid_to",
                        None,
                        datetime(
                            2024,
                            1,
                            2,
                            tzinfo=timezone.utc,
                        ),
                    ),
                    FieldChange(
                        "valid_to",
                        None,
                        datetime(
                            2024,
                            1,
                            2,
                            tzinfo=timezone.utc,
                        ),
                    ),
                ),
            },
            ValueError,
            "duplicate deployment UPDATE field",
        ),
        (
            {
                "changes": (
                    FieldChange(
                        "valid_to",
                        None,
                        datetime(
                            2024,
                            1,
                            3,
                            tzinfo=timezone.utc,
                        ),
                    ),
                ),
            },
            ValueError,
            (
                "change.after does not match "
                "resolved values"
            ),
        ),
    ],
)
def test_deployment_update_rejects_invalid_input_before_sql(
    overrides,
    error_type,
    message,
):
    connection = FakeUpdateConnection()
    item = replace(
        _deployment_update(),
        **overrides,
    )

    with pytest.raises(error_type, match=message):
        update_metadata_item(
            connection,
            item,
            ApplyContext(),
        )

    assert connection.calls == []


def test_deployment_update_rejects_stale_plan():
    connection = FakeUpdateConnection(returned_row=None)

    with pytest.raises(ApplyError) as caught:
        update_metadata_item(
            connection,
            _deployment_update(),
            ApplyContext(),
        )

    assert caught.value.code == ApplyErrorCode.STALE_PLAN
    assert "deployment_id=81" in str(caught.value)
    assert len(connection.calls) == 1


@pytest.mark.parametrize(
    ("field", "old_id", "new_id", "plan_id", "column"),
    [
        (
            "sensor",
            31,
            32,
            "sensors[0]",
            "sensor_id",
        ),
        (
            "location",
            41,
            42,
            "locations[0]",
            "location_id",
        ),
        (
            "variable",
            51,
            52,
            "variables[0]",
            "variable_id",
        ),
    ],
)
@pytest.mark.parametrize("planned", [False, True])
def test_deployment_update_resolves_relationship(
    field,
    old_id,
    new_id,
    plan_id,
    column,
    planned,
):
    connection = FakeUpdateConnection()
    context = ApplyContext()
    original = _deployment_update()

    if planned:
        after = PlannedRef(
            resource_type=field,
            plan_id=plan_id,
        )
        context.register(
            plan_id=plan_id,
            resource_type=field,
            database_id=new_id,
        )
    else:
        after = ExistingRef(
            resource_type=field,
            database_id=new_id,
        )

    before = ExistingRef(
        resource_type=field,
        database_id=old_id,
    )

    item = replace(
        original,
        values=replace(
            original.values,
            **{field: after},
        ),
        changes=(
            FieldChange(
                field=field,
                before=before,
                after=after,
                identity_change=True,
            ),
        ),
    )

    result = update_metadata_item(
        connection,
        item,
        context,
    )

    assert result == ApplyItemResult(
        plan_id="updates.deployments[0]",
        resource_type="deployment",
        action=PlanAction.UPDATE,
        database_id=81,
    )
    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        f'UPDATE "deployments" SET "{column}" = %s '
        'WHERE "deployment_id" = %s '
        f'AND "{column}" IS NOT DISTINCT FROM %s '
        'RETURNING "deployment_id"'
    )
    assert params == (new_id, 81, old_id)


@pytest.mark.parametrize(
    ("field", "old_id", "new_id", "plan_id"),
    [
        (
            "sensor",
            31,
            32,
            "sensors[0]",
        ),
        (
            "location",
            41,
            42,
            "locations[0]",
        ),
        (
            "variable",
            51,
            52,
            "variables[0]",
        ),
    ],
)
@pytest.mark.parametrize(
    "registered_resource_type",
    [
        None,
        "site",
    ],
)
def test_deployment_update_rejects_unavailable_planned_relationship(
    field,
    old_id,
    new_id,
    plan_id,
    registered_resource_type,
):
    connection = FakeUpdateConnection()
    context = ApplyContext()
    original = _deployment_update()

    after = PlannedRef(
        resource_type=field,
        plan_id=plan_id,
    )
    before = ExistingRef(
        resource_type=field,
        database_id=old_id,
    )

    if registered_resource_type is not None:
        context.register(
            plan_id=plan_id,
            resource_type=registered_resource_type,
            database_id=new_id,
        )

    item = replace(
        original,
        values=replace(
            original.values,
            **{field: after},
        ),
        changes=(
            FieldChange(
                field=field,
                before=before,
                after=after,
                identity_change=True,
            ),
        ),
    )

    with pytest.raises(ApplyError) as caught:
        update_metadata_item(
            connection,
            item,
            context,
        )

    assert (
        caught.value.code
        == ApplyErrorCode.UNRESOLVED_PLANNED_REF
    )
    assert connection.calls == []


def test_deployment_update_combines_relationships_and_timestamps():
    connection = FakeUpdateConnection()
    context = ApplyContext()
    original = _deployment_update()

    old_sensor = ExistingRef("sensor", 31)
    old_location = ExistingRef("location", 41)
    old_variable = ExistingRef("variable", 51)

    new_sensor = PlannedRef(
        resource_type="sensor",
        plan_id="sensors[0]",
    )
    new_location = ExistingRef("location", 42)
    new_variable = PlannedRef(
        resource_type="variable",
        plan_id="variables[0]",
    )

    context.register(
        plan_id="sensors[0]",
        resource_type="sensor",
        database_id=32,
    )
    context.register(
        plan_id="variables[0]",
        resource_type="variable",
        database_id=52,
    )

    old_valid_from = datetime(
        2024,
        1,
        1,
        0,
        0,
        tzinfo=timezone.utc,
    )
    old_valid_to = datetime(
        2024,
        1,
        2,
        0,
        0,
        tzinfo=timezone.utc,
    )
    new_valid_from = datetime(
        2024,
        1,
        2,
        0,
        0,
        tzinfo=timezone.utc,
    )
    new_valid_to = datetime(
        2024,
        1,
        3,
        0,
        0,
        tzinfo=timezone.utc,
    )

    item = replace(
        original,
        values=ResolvedDeploymentValues(
            sensor=new_sensor,
            location=new_location,
            variable=new_variable,
            valid_from=new_valid_from,
            valid_to=new_valid_to,
        ),
        changes=(
            FieldChange(
                "sensor",
                old_sensor,
                new_sensor,
                identity_change=True,
            ),
            FieldChange(
                "location",
                old_location,
                new_location,
                identity_change=True,
            ),
            FieldChange(
                "variable",
                old_variable,
                new_variable,
                identity_change=True,
            ),
            FieldChange(
                "valid_from",
                old_valid_from,
                new_valid_from,
                identity_change=True,
            ),
            FieldChange(
                "valid_to",
                old_valid_to,
                new_valid_to,
            ),
        ),
    )

    result = update_metadata_item(
        connection,
        item,
        context,
    )

    assert result == ApplyItemResult(
        plan_id="updates.deployments[0]",
        resource_type="deployment",
        action=PlanAction.UPDATE,
        database_id=81,
    )
    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        'UPDATE "deployments" '
        'SET "sensor_id" = %s, '
        '"location_id" = %s, '
        '"variable_id" = %s, '
        '"valid_from" = %s, '
        '"valid_to" = %s '
        'WHERE "deployment_id" = %s '
        'AND "sensor_id" IS NOT DISTINCT FROM %s '
        'AND "location_id" IS NOT DISTINCT FROM %s '
        'AND "variable_id" IS NOT DISTINCT FROM %s '
        'AND "valid_from" IS NOT DISTINCT FROM %s '
        'AND "valid_to" IS NOT DISTINCT FROM %s '
        'RETURNING "deployment_id"'
    )
    assert params == (
        32,
        42,
        52,
        new_valid_from,
        new_valid_to,
        81,
        31,
        41,
        51,
        old_valid_from,
        old_valid_to,
    )


def test_deployment_update_resolves_all_changes_before_sql():
    connection = FakeUpdateConnection()
    original = _deployment_update()

    old_valid_to = datetime(
        2024,
        1,
        2,
        0,
        0,
        tzinfo=timezone.utc,
    )
    new_valid_to = datetime(
        2024,
        1,
        3,
        0,
        0,
        tzinfo=timezone.utc,
    )
    old_sensor = ExistingRef("sensor", 31)
    new_sensor = PlannedRef(
        resource_type="sensor",
        plan_id="sensors[0]",
    )

    item = replace(
        original,
        values=replace(
            original.values,
            sensor=new_sensor,
            valid_to=new_valid_to,
        ),
        changes=(
            FieldChange(
                "valid_to",
                old_valid_to,
                new_valid_to,
            ),
            FieldChange(
                "sensor",
                old_sensor,
                new_sensor,
                identity_change=True,
            ),
        ),
    )

    with pytest.raises(ApplyError) as caught:
        update_metadata_item(
            connection,
            item,
            ApplyContext(),
        )

    assert (
        caught.value.code
        == ApplyErrorCode.UNRESOLVED_PLANNED_REF
    )
    assert connection.calls == []


def test_deployment_combined_update_rejects_stale_plan():
    connection = FakeUpdateConnection(returned_row=None)
    original = _deployment_update()

    old_location = ExistingRef("location", 41)
    new_location = ExistingRef("location", 42)
    old_valid_to = datetime(
        2024,
        1,
        2,
        0,
        0,
        tzinfo=timezone.utc,
    )
    new_valid_to = datetime(
        2024,
        1,
        3,
        0,
        0,
        tzinfo=timezone.utc,
    )

    item = replace(
        original,
        values=replace(
            original.values,
            location=new_location,
            valid_to=new_valid_to,
        ),
        changes=(
            FieldChange(
                "location",
                old_location,
                new_location,
                identity_change=True,
            ),
            FieldChange(
                "valid_to",
                old_valid_to,
                new_valid_to,
            ),
        ),
    )

    with pytest.raises(ApplyError) as caught:
        update_metadata_item(
            connection,
            item,
            ApplyContext(),
        )

    assert caught.value.code == ApplyErrorCode.STALE_PLAN
    assert "deployment_id=81" in str(caught.value)
    assert len(connection.calls) == 1
