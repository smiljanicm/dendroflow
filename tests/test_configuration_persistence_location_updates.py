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
    ExistingRef,
    FieldChange,
    PlanAction,
    PlannedRef,
    ResolvedLocationValues,
    ResolvedPlanItem,
)


class FakeUpdateConnection:
    def __init__(self, returned_row=(71,)):
        self.returned_row = returned_row
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))
        return self

    def fetchone(self):
        return self.returned_row


def _location_update() -> ResolvedPlanItem:
    return ResolvedPlanItem(
        plan_id="updates.locations[0]",
        resource_type="location",
        action=PlanAction.UPDATE,
        database_id=71,
        values=ResolvedLocationValues(
            site=ExistingRef("site", 11),
            location_type=ExistingRef("location_type", 21),
            latitude=54.10,
            longitude=13.40,
            height_above_ground=1.50,
            azimuth=180.0,
        ),
        changes=(
            FieldChange(
                field="height_above_ground",
                before=1.30,
                after=1.50,
            ),
        ),
    )


@pytest.mark.parametrize(
    ("field", "before", "after"),
    [
        ("latitude", 54.10, 54.20),
        ("longitude", 13.40, 13.50),
        ("height_above_ground", 1.30, 1.50),
        ("azimuth", 180.0, 190.0),
        ("latitude", 54.10, 0.0),
        ("longitude", 13.40, 0.0),
        ("height_above_ground", 1.30, 0.0),
        ("azimuth", 180.0, 0.0),
        ("height_above_ground", None, 1.50),
        ("height_above_ground", 1.30, None),
        ("azimuth", None, 180.0),
        ("azimuth", 180.0, None),
    ],
)
def test_location_update_persists_scalar_change(
    field,
    before,
    after,
):
    connection = FakeUpdateConnection()
    original = _location_update()

    item = replace(
        original,
        values=replace(original.values, **{field: after}),
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
        plan_id="updates.locations[0]",
        resource_type="location",
        action=PlanAction.UPDATE,
        database_id=71,
    )
    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        f'UPDATE "locations" SET "{field}" = %s '
        'WHERE "location_id" = %s '
        f'AND "{field}" IS NOT DISTINCT FROM %s '
        'RETURNING "location_id"'
    )
    assert params == (after, 71, before)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ((54.10, 13.40), (54.20, 13.50)),
        ((None, None), (54.10, 13.40)),
        ((54.10, 13.40), (None, None)),
    ],
)
def test_location_update_persists_coordinate_pair(before, after):
    connection = FakeUpdateConnection()
    original = _location_update()

    item = replace(
        original,
        values=replace(
            original.values,
            latitude=after[0],
            longitude=after[1],
        ),
        changes=(
            FieldChange("latitude", before[0], after[0]),
            FieldChange("longitude", before[1], after[1]),
        ),
    )

    update_metadata_item(connection, item, ApplyContext())

    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        'UPDATE "locations" SET "latitude" = %s, "longitude" = %s '
        'WHERE "location_id" = %s '
        'AND "latitude" IS NOT DISTINCT FROM %s '
        'AND "longitude" IS NOT DISTINCT FROM %s '
        'RETURNING "location_id"'
    )
    assert params == (
        after[0],
        after[1],
        71,
        before[0],
        before[1],
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
            "requires ResolvedLocationValues",
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
            "unsupported location UPDATE field",
        ),
        (
            {
                "changes": (
                    FieldChange("azimuth", 90.0, 180.0),
                    FieldChange("azimuth", 90.0, 180.0),
                ),
            },
            ValueError,
            "duplicate location UPDATE field",
        ),
        (
            {
                "changes": (
                    FieldChange("azimuth", 90.0, 270.0),
                ),
            },
            ValueError,
            "change.after does not match resolved values",
        ),
    ],
)
def test_location_update_rejects_invalid_input_before_sql(
    overrides,
    error_type,
    message,
):
    connection = FakeUpdateConnection()
    item = replace(_location_update(), **overrides)

    with pytest.raises(error_type, match=message):
        update_metadata_item(
            connection,
            item,
            ApplyContext(),
        )

    assert connection.calls == []


def test_location_update_rejects_stale_plan():
    connection = FakeUpdateConnection(returned_row=None)

    with pytest.raises(ApplyError) as caught:
        update_metadata_item(
            connection,
            _location_update(),
            ApplyContext(),
        )

    assert caught.value.code == ApplyErrorCode.STALE_PLAN
    assert "location_id=71" in str(caught.value)
    assert len(connection.calls) == 1


@pytest.mark.parametrize(
    ("field", "old_id", "new_id", "plan_id", "column"),
    [
        ("site", 11, 12, "sites[0]", "site_id"),
        (
            "location_type",
            21,
            22,
            "location_types[0]",
            "location_type_id",
        ),
    ],
)
@pytest.mark.parametrize("planned", [False, True])
def test_location_update_resolves_relationship(
    field,
    old_id,
    new_id,
    plan_id,
    column,
    planned,
):
    connection = FakeUpdateConnection()
    context = ApplyContext()

    if planned:
        context.register(
            plan_id=plan_id,
            resource_type=field,
            database_id=new_id,
        )
        new_reference = PlannedRef(
            resource_type=field,
            plan_id=plan_id,
        )
    else:
        new_reference = ExistingRef(
            resource_type=field,
            database_id=new_id,
        )

    original = _location_update()
    item = replace(
        original,
        values=replace(
            original.values,
            **{field: new_reference},
        ),
        changes=(
            FieldChange(
                field=field,
                before=ExistingRef(field, old_id),
                after=new_reference,
                identity_change=field == "site",
            ),
        ),
    )

    result = update_metadata_item(
        connection,
        item,
        context,
    )

    assert result == ApplyItemResult(
        plan_id="updates.locations[0]",
        resource_type="location",
        action=PlanAction.UPDATE,
        database_id=71,
    )
    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        f'UPDATE "locations" SET "{column}" = %s '
        'WHERE "location_id" = %s '
        f'AND "{column}" IS NOT DISTINCT FROM %s '
        'RETURNING "location_id"'
    )
    assert params == (new_id, 71, old_id)


def test_location_update_combines_relationships_and_scalar_change():
    connection = FakeUpdateConnection()
    context = ApplyContext()

    context.register(
        plan_id="sites[0]",
        resource_type="site",
        database_id=12,
    )
    context.register(
        plan_id="location_types[0]",
        resource_type="location_type",
        database_id=22,
    )

    new_site = PlannedRef("site", "sites[0]")
    new_location_type = PlannedRef(
        "location_type",
        "location_types[0]",
    )

    original = _location_update()
    item = replace(
        original,
        values=replace(
            original.values,
            site=new_site,
            location_type=new_location_type,
            height_above_ground=1.50,
        ),
        changes=(
            FieldChange(
                "site",
                ExistingRef("site", 11),
                new_site,
                identity_change=True,
            ),
            FieldChange(
                "location_type",
                ExistingRef("location_type", 21),
                new_location_type,
                identity_change=False,
            ),
            FieldChange(
                "height_above_ground",
                1.30,
                1.50,
            ),
        ),
    )

    result = update_metadata_item(
        connection,
        item,
        context,
    )

    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        'UPDATE "locations" '
        'SET "site_id" = %s, "location_type_id" = %s, '
        '"height_above_ground" = %s '
        'WHERE "location_id" = %s '
        'AND "site_id" IS NOT DISTINCT FROM %s '
        'AND "location_type_id" IS NOT DISTINCT FROM %s '
        'AND "height_above_ground" IS NOT DISTINCT FROM %s '
        'RETURNING "location_id"'
    )
    assert params == (
        12,
        22,
        1.50,
        71,
        11,
        21,
        1.30,
    )
    assert result.database_id == 71


@pytest.mark.parametrize(
    ("field", "old_id", "plan_id"),
    [
        ("site", 11, "sites[0]"),
        ("location_type", 21, "location_types[0]"),
    ],
)
@pytest.mark.parametrize(
    "registered_resource_type",
    [None, "sensor"],
)
def test_location_update_rejects_unavailable_planned_relationship(
    field,
    old_id,
    plan_id,
    registered_resource_type,
):
    connection = FakeUpdateConnection()
    context = ApplyContext()

    if registered_resource_type is not None:
        context.register(
            plan_id=plan_id,
            resource_type=registered_resource_type,
            database_id=99,
        )

    new_reference = PlannedRef(
        resource_type=field,
        plan_id=plan_id,
    )

    original = _location_update()
    item = replace(
        original,
        values=replace(
            original.values,
            **{field: new_reference},
        ),
        changes=original.changes + (
            FieldChange(
                field=field,
                before=ExistingRef(field, old_id),
                after=new_reference,
                identity_change=field == "site",
            ),
        ),
    )

    with pytest.raises(ApplyError) as caught:
        update_metadata_item(
            connection,
            item,
            context,
        )

    assert caught.value.code == ApplyErrorCode.UNRESOLVED_PLANNED_REF
    assert connection.calls == []


def test_location_relationship_update_rejects_stale_plan():
    connection = FakeUpdateConnection(returned_row=None)
    original = _location_update()
    new_site = ExistingRef("site", 12)

    item = replace(
        original,
        values=replace(
            original.values,
            site=new_site,
        ),
        changes=(
            FieldChange(
                field="site",
                before=ExistingRef("site", 11),
                after=new_site,
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

    assert caught.value.code == ApplyErrorCode.STALE_PLAN
    assert "location_id=71" in str(caught.value)
    assert len(connection.calls) == 1

    _, params = connection.calls[0]

    assert params == (12, 71, 11)

