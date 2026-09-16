from dataclasses import replace

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
    FieldChange,
    PlanAction,
    ResolvedLocationTypeValues,
    ResolvedPlanItem,
    ResolvedSensorTypeValues,
    ResolvedVariableValues,
)


class FakeUpdateConnection:
    def __init__(self, returned_row=(21,)):
        self.returned_row = returned_row
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))
        return self

    def fetchone(self):
        return self.returned_row


def _location_type_update() -> ResolvedPlanItem:
    return ResolvedPlanItem(
        plan_id="updates.location_types[0]",
        resource_type="location_type",
        action=PlanAction.UPDATE,
        database_id=21,
        values=ResolvedLocationTypeValues(
            type="stem",
            description="Existing description",
        ),
        changes=(
            FieldChange(
                field="type",
                before="trunk",
                after="stem",
                identity_change=True,
            ),
        ),
    )


def test_location_type_update_persists_identity_correction():
    connection = FakeUpdateConnection()
    item = _location_type_update()

    result = update_metadata_item(
        connection,
        item,
        ApplyContext(),
    )

    assert result == ApplyItemResult(
        plan_id="updates.location_types[0]",
        resource_type="location_type",
        action=PlanAction.UPDATE,
        database_id=21,
    )
    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        'UPDATE "location_types" SET "type" = %s '
        'WHERE "location_type_id" = %s '
        'AND "type" IS NOT DISTINCT FROM %s '
        'RETURNING "location_type_id"'
    )
    assert params == ("stem", 21, "trunk")


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (None, "New description"),
        ("Old description", None),
    ],
)
def test_location_type_update_handles_nullable_description(
    before,
    after,
):
    connection = FakeUpdateConnection()
    item = replace(
        _location_type_update(),
        values=ResolvedLocationTypeValues(
            type="stem",
            description=after,
        ),
        changes=(
            FieldChange(
                field="description",
                before=before,
                after=after,
            ),
        ),
    )

    update_metadata_item(connection, item, ApplyContext())

    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        'UPDATE "location_types" SET "description" = %s '
        'WHERE "location_type_id" = %s '
        'AND "description" IS NOT DISTINCT FROM %s '
        'RETURNING "location_type_id"'
    )
    assert params == (after, 21, before)


def test_location_type_update_writes_and_guards_both_fields():
    connection = FakeUpdateConnection()
    item = replace(
        _location_type_update(),
        values=ResolvedLocationTypeValues(
            type="stem",
            description="New description",
        ),
        changes=(
            FieldChange(
                field="type",
                before="trunk",
                after="stem",
                identity_change=True,
            ),
            FieldChange(
                field="description",
                before="Old description",
                after="New description",
            ),
        ),
    )

    update_metadata_item(connection, item, ApplyContext())

    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        'UPDATE "location_types" '
        'SET "type" = %s, "description" = %s '
        'WHERE "location_type_id" = %s '
        'AND "type" IS NOT DISTINCT FROM %s '
        'AND "description" IS NOT DISTINCT FROM %s '
        'RETURNING "location_type_id"'
    )
    assert params == (
        "stem",
        "New description",
        21,
        "trunk",
        "Old description",
    )


@pytest.mark.parametrize(
    ("overrides", "error_type", "message"),
    [
        (
            {
                "action": PlanAction.CREATE,
                "database_id": None,
                "changes": (),
            },
            ValueError,
            "requires UPDATE action",
        ),
        (
            {
                "action": PlanAction.REUSE,
                "changes": (),
            },
            ValueError,
            "requires UPDATE action",
        ),
        (
            {"values": object()},
            TypeError,
            "requires ResolvedLocationTypeValues",
        ),
                (
            {"database_id": 0},
            ValueError,
            "positive integer database_id",
        ),
        (
            {"database_id": -1},
            ValueError,
            "positive integer database_id",
        ),
        (
            {"database_id": True},
            ValueError,
            "positive integer database_id",
        ),
        (
            {"database_id": 1.5},
            ValueError,
            "positive integer database_id",
        ),
        (
            {"database_id": "21"},
            ValueError,
            "positive integer database_id",
        ),
        (
            {
                "changes": (
                    FieldChange("unknown", None, "value"),
                ),
            },
            ValueError,
            "unsupported location_type UPDATE field",
        ),
        (
            {
                "changes": (
                    FieldChange("type", "trunk", "stem"),
                    FieldChange("type", "trunk", "stem"),
                ),
            },
            ValueError,
            "duplicate location_type UPDATE field",
        ),
        (
            {
                "changes": (
                    FieldChange("type", "trunk", "Different type"),
                ),
            },
            ValueError,
            "change.after does not match resolved values",
        ),
    ],
)
def test_location_type_update_rejects_invalid_input_before_sql(
    overrides,
    error_type,
    message,
):
    connection = FakeUpdateConnection()
    item = replace(_location_type_update(), **overrides)

    with pytest.raises(error_type, match=message):
        update_metadata_item(connection, item, ApplyContext())

    assert connection.calls == []


def test_location_type_update_rejects_stale_plan():
    connection = FakeUpdateConnection(returned_row=None)

    with pytest.raises(ApplyError) as caught:
        update_metadata_item(
            connection,
            _location_type_update(),
            ApplyContext(),
        )

    assert caught.value.code == ApplyErrorCode.STALE_PLAN
    assert "location_type_id=21" in str(caught.value)
    assert len(connection.calls) == 1


@pytest.fixture(params=["sensor_type", "variable"])
def simple_update_case(request):
    if request.param == "sensor_type":
        item = ResolvedPlanItem(
            plan_id="updates.sensor_types[0]",
            resource_type="sensor_type",
            action=PlanAction.UPDATE,
            database_id=21,
            values=ResolvedSensorTypeValues(
                type="dendrometer",
                description="Existing description",
            ),
            changes=(
                FieldChange(
                    field="type",
                    before="Old type",
                    after="dendrometer",
                    identity_change=True,
                ),
            ),
        )
        return item, "sensor_types", "sensor_type_id", "type"

    item = ResolvedPlanItem(
        plan_id="updates.variables[0]",
        resource_type="variable",
        action=PlanAction.UPDATE,
        database_id=21,
        values=ResolvedVariableValues(
            variable="stem_radius",
            derived=False,
            description="Existing description",
        ),
        changes=(
            FieldChange(
                field="variable",
                before="Old variable",
                after="stem_radius",
                identity_change=True,
            ),
        ),
    )
    return item, "variables", "variable_id", "variable"


def test_simple_update_persists_identity_correction(simple_update_case):
    item, table, primary_key, identity_field = simple_update_case
    connection = FakeUpdateConnection()

    result = update_metadata_item(connection, item, ApplyContext())

    assert result == ApplyItemResult(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        action=PlanAction.UPDATE,
        database_id=21,
    )
    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        f'UPDATE "{table}" SET "{identity_field}" = %s '
        f'WHERE "{primary_key}" = %s '
        f'AND "{identity_field}" IS NOT DISTINCT FROM %s '
        f'RETURNING "{primary_key}"'
    )
    assert params == (
        item.changes[0].after,
        21,
        item.changes[0].before,
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (None, "New description"),
        ("Old description", None),
    ],
)
def test_simple_update_handles_nullable_description(
    simple_update_case,
    before,
    after,
):
    original, table, primary_key, _ = simple_update_case
    item = replace(
        original,
        values=replace(original.values, description=after),
        changes=(
            FieldChange("description", before, after),
        ),
    )
    connection = FakeUpdateConnection()

    update_metadata_item(connection, item, ApplyContext())

    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        f'UPDATE "{table}" SET "description" = %s '
        f'WHERE "{primary_key}" = %s '
        'AND "description" IS NOT DISTINCT FROM %s '
        f'RETURNING "{primary_key}"'
    )
    assert params == (after, 21, before)


def test_simple_update_guards_multiple_fields(simple_update_case):
    original, table, primary_key, identity_field = simple_update_case
    item = replace(
        original,
        values=replace(
            original.values,
            description="New description",
        ),
        changes=original.changes + (
            FieldChange(
                "description",
                "Existing description",
                "New description",
            ),
        ),
    )
    connection = FakeUpdateConnection()

    update_metadata_item(connection, item, ApplyContext())

    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        f'UPDATE "{table}" '
        f'SET "{identity_field}" = %s, "description" = %s '
        f'WHERE "{primary_key}" = %s '
        f'AND "{identity_field}" IS NOT DISTINCT FROM %s '
        'AND "description" IS NOT DISTINCT FROM %s '
        f'RETURNING "{primary_key}"'
    )
    assert params == (
        original.changes[0].after,
        "New description",
        21,
        original.changes[0].before,
        "Existing description",
    )


@pytest.mark.parametrize(
    ("overrides", "error_type", "message"),
    [
        (
            {
                "action": PlanAction.CREATE,
                "database_id": None,
                "changes": (),
            },
            ValueError,
            "requires UPDATE action",
        ),
        (
            {
                "action": PlanAction.REUSE,
                "changes": (),
            },
            ValueError,
            "requires UPDATE action",
        ),
        (
            {"values": object()},
            TypeError,
            "UPDATE requires Resolved",
        ),
        (
            {"database_id": 0},
            ValueError,
            "positive integer database_id",
        ),
        (
            {
                "changes": (
                    FieldChange("unknown", None, "value"),
                ),
            },
            ValueError,
            "unsupported .* UPDATE field",
        ),
        (
            {
                "changes": (
                    FieldChange(
                        "description", None, "Existing description"
                    ),
                    FieldChange(
                        "description", None, "Existing description"
                    ),
                ),
            },
            ValueError,
            "duplicate .* UPDATE field",
        ),
        (
            {
                "changes": (
                    FieldChange("description", None, "Different"),
                ),
            },
            ValueError,
            "change.after does not match resolved values",
        ),
    ],
)
def test_simple_update_rejects_invalid_input_before_sql(
    simple_update_case,
    overrides,
    error_type,
    message,
):
    original, _, _, _ = simple_update_case
    item = replace(original, **overrides)
    connection = FakeUpdateConnection()

    with pytest.raises(error_type, match=message):
        update_metadata_item(connection, item, ApplyContext())

    assert connection.calls == []


def test_simple_update_rejects_stale_plan(simple_update_case):
    item, _, primary_key, _ = simple_update_case
    connection = FakeUpdateConnection(returned_row=None)

    with pytest.raises(ApplyError) as caught:
        update_metadata_item(connection, item, ApplyContext())

    assert caught.value.code == ApplyErrorCode.STALE_PLAN
    assert f"{primary_key}=21" in str(caught.value)
    assert len(connection.calls) == 1


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (False, True),
        (True, False),
    ],
)
def test_variable_update_persists_derived_boolean(before, after):
    connection = FakeUpdateConnection()
    item = ResolvedPlanItem(
        plan_id="updates.variables[0]",
        resource_type="variable",
        action=PlanAction.UPDATE,
        database_id=21,
        values=ResolvedVariableValues(
            variable="stem_radius",
            derived=after,
            description=None,
        ),
        changes=(
            FieldChange(
                field="derived",
                before=before,
                after=after,
            ),
        ),
    )

    result = update_metadata_item(
        connection,
        item,
        ApplyContext(),
    )

    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        'UPDATE "variables" SET "derived" = %s '
        'WHERE "variable_id" = %s '
        'AND "derived" IS NOT DISTINCT FROM %s '
        'RETURNING "variable_id"'
    )
    assert params == (after, 21, before)
    assert params[0] is after
    assert params[2] is before
    assert result.database_id == 21

