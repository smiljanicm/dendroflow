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
    ResolvedPlanItem,
    ResolvedSensorValues,
)


class FakeUpdateConnection:
    def __init__(self, returned_row=(17,)):
        self.returned_row = returned_row
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))
        return self

    def fetchone(self):
        return self.returned_row


def _sensor_update() -> ResolvedPlanItem:
    return ResolvedPlanItem(
        plan_id="updates.sensors[0]",
        resource_type="sensor",
        action=PlanAction.UPDATE,
        database_id=17,
        values=ResolvedSensorValues(
            serial_number="NEW123",
            sensor_model=ExistingRef("sensor_model", 3),
            description="Existing description",
        ),
        changes=(
            FieldChange(
                field="serial_number",
                before="OLD123",
                after="NEW123",
                identity_change=True,
            ),
        ),
    )


def test_sensor_update_persists_serial_number_correction():
    connection = FakeUpdateConnection()
    item = _sensor_update()

    result = update_metadata_item(
        connection,
        item,
        ApplyContext(),
    )

    assert result == ApplyItemResult(
        plan_id="updates.sensors[0]",
        resource_type="sensor",
        action=PlanAction.UPDATE,
        database_id=17,
    )
    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        'UPDATE "sensors" SET "serial_number" = %s '
        'WHERE "sensor_id" = %s '
        'AND "serial_number" IS NOT DISTINCT FROM %s '
        'RETURNING "sensor_id"'
    )
    assert params == ("NEW123", 17, "OLD123")


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (None, "New description"),
        ("Old description", None),
    ],
)
def test_sensor_update_handles_nullable_description(before, after):
    connection = FakeUpdateConnection()
    original = _sensor_update()

    item = replace(
        original,
        values=replace(
            original.values,
            description=after,
        ),
        changes=(
            FieldChange("description", before, after),
        ),
    )

    update_metadata_item(connection, item, ApplyContext())

    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        'UPDATE "sensors" SET "description" = %s '
        'WHERE "sensor_id" = %s '
        'AND "description" IS NOT DISTINCT FROM %s '
        'RETURNING "sensor_id"'
    )
    assert params == (after, 17, before)


@pytest.mark.parametrize("planned", [False, True])
def test_sensor_update_resolves_sensor_model(planned):
    connection = FakeUpdateConnection()
    context = ApplyContext()

    if planned:
        context.register(
            plan_id="sensor_models[0]",
            resource_type="sensor_model",
            database_id=4,
        )
        new_model = PlannedRef(
            resource_type="sensor_model",
            plan_id="sensor_models[0]",
        )
    else:
        new_model = ExistingRef(
            resource_type="sensor_model",
            database_id=4,
        )

    original = _sensor_update()
    item = replace(
        original,
        values=replace(
            original.values,
            sensor_model=new_model,
        ),
        changes=(
            FieldChange(
                field="sensor_model",
                before=ExistingRef("sensor_model", 3),
                after=new_model,
                identity_change=True,
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
        'UPDATE "sensors" SET "sensor_model_id" = %s '
        'WHERE "sensor_id" = %s '
        'AND "sensor_model_id" IS NOT DISTINCT FROM %s '
        'RETURNING "sensor_id"'
    )
    assert params == (4, 17, 3)
    assert result.database_id == 17
    assert result.action == PlanAction.UPDATE


def test_sensor_update_combines_scalar_and_relationship_changes():
    connection = FakeUpdateConnection()
    context = ApplyContext()

    context.register(
        plan_id="sensor_models[0]",
        resource_type="sensor_model",
        database_id=4,
    )

    new_model = PlannedRef(
        resource_type="sensor_model",
        plan_id="sensor_models[0]",
    )

    item = replace(
        _sensor_update(),
        values=ResolvedSensorValues(
            serial_number="NEW123",
            sensor_model=new_model,
            description=None,
        ),
        changes=(
            FieldChange(
                "serial_number",
                "OLD123",
                "NEW123",
                identity_change=True,
            ),
            FieldChange(
                "description",
                "Existing description",
                None,
            ),
            FieldChange(
                "sensor_model",
                ExistingRef("sensor_model", 3),
                new_model,
                identity_change=True,
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
        'UPDATE "sensors" '
        'SET "serial_number" = %s, "description" = %s, '
        '"sensor_model_id" = %s '
        'WHERE "sensor_id" = %s '
        'AND "serial_number" IS NOT DISTINCT FROM %s '
        'AND "description" IS NOT DISTINCT FROM %s '
        'AND "sensor_model_id" IS NOT DISTINCT FROM %s '
        'RETURNING "sensor_id"'
    )
    assert params == (
        "NEW123",
        None,
        4,
        17,
        "OLD123",
        "Existing description",
        3,
    )
    assert result.database_id == 17


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
            "requires ResolvedSensorValues",
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
            "unsupported sensor UPDATE field",
        ),
        (
            {
                "changes": (
                    FieldChange("serial_number", "OLD123", "NEW123"),
                    FieldChange("serial_number", "OLD123", "NEW123"),
                ),
            },
            ValueError,
            "duplicate sensor UPDATE field",
        ),
        (
            {
                "changes": (
                    FieldChange("serial_number", "OLD123", "Different"),
                ),
            },
            ValueError,
            "change.after does not match resolved values",
        ),
    ],
)
def test_sensor_update_rejects_invalid_input_before_sql(
    overrides,
    error_type,
    message,
):
    connection = FakeUpdateConnection()
    item = replace(_sensor_update(), **overrides)

    with pytest.raises(error_type, match=message):
        update_metadata_item(
            connection,
            item,
            ApplyContext(),
        )

    assert connection.calls == []


@pytest.mark.parametrize(
    "registered_resource_type",
    [None, "site"],
)
def test_sensor_update_rejects_unavailable_planned_model(
    registered_resource_type,
):
    connection = FakeUpdateConnection()
    context = ApplyContext()

    if registered_resource_type is not None:
        context.register(
            plan_id="sensor_models[0]",
            resource_type=registered_resource_type,
            database_id=4,
        )

    new_model = PlannedRef(
        resource_type="sensor_model",
        plan_id="sensor_models[0]",
    )

    original = _sensor_update()
    item = replace(
        original,
        values=replace(
            original.values,
            sensor_model=new_model,
        ),
        changes=original.changes + (
            FieldChange(
                field="sensor_model",
                before=ExistingRef("sensor_model", 3),
                after=new_model,
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

    assert caught.value.code == ApplyErrorCode.UNRESOLVED_PLANNED_REF
    assert connection.calls == []


def test_sensor_update_rejects_stale_plan():
    connection = FakeUpdateConnection(returned_row=None)

    with pytest.raises(ApplyError) as caught:
        update_metadata_item(
            connection,
            _sensor_update(),
            ApplyContext(),
        )

    assert caught.value.code == ApplyErrorCode.STALE_PLAN
    assert "sensor_id=17" in str(caught.value)
    assert len(connection.calls) == 1


