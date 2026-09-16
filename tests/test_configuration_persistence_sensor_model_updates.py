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
    ResolvedSensorModelValues,
)


class FakeUpdateConnection:
    def __init__(self, returned_row=(31,)):
        self.returned_row = returned_row
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))
        return self

    def fetchone(self):
        return self.returned_row


def _sensor_model_update() -> ResolvedPlanItem:
    return ResolvedPlanItem(
        plan_id="updates.sensor_models[0]",
        resource_type="sensor_model",
        action=PlanAction.UPDATE,
        database_id=31,
        values=ResolvedSensorModelValues(
            manufacturer="New manufacturer",
            model="M1",
            sensor_type=ExistingRef("sensor_type", 2),
        ),
        changes=(
            FieldChange(
                field="manufacturer",
                before="Old manufacturer",
                after="New manufacturer",
                identity_change=True,
            ),
        ),
    )


@pytest.mark.parametrize(
    (
        "manufacturer",
        "model",
        "changes",
        "expected_set",
        "expected_guards",
        "expected_params",
    ),
    [
        (
            "New manufacturer",
            "M1",
            (
                FieldChange(
                    "manufacturer",
                    "Old manufacturer",
                    "New manufacturer",
                    identity_change=True,
                ),
            ),
            '"manufacturer" = %s',
            '"manufacturer" IS NOT DISTINCT FROM %s',
            ("New manufacturer", 31, "Old manufacturer"),
        ),
        (
            "Existing manufacturer",
            "M2",
            (
                FieldChange(
                    "model",
                    "M1",
                    "M2",
                    identity_change=True,
                ),
            ),
            '"model" = %s',
            '"model" IS NOT DISTINCT FROM %s',
            ("M2", 31, "M1"),
        ),
        (
            "New manufacturer",
            "M2",
            (
                FieldChange(
                    "manufacturer",
                    "Old manufacturer",
                    "New manufacturer",
                    identity_change=True,
                ),
                FieldChange(
                    "model",
                    "M1",
                    "M2",
                    identity_change=True,
                ),
            ),
            '"manufacturer" = %s, "model" = %s',
            (
                '"manufacturer" IS NOT DISTINCT FROM %s '
                'AND "model" IS NOT DISTINCT FROM %s'
            ),
            (
                "New manufacturer",
                "M2",
                31,
                "Old manufacturer",
                "M1",
            ),
        ),
    ],
)
def test_sensor_model_update_persists_scalar_corrections(
    manufacturer,
    model,
    changes,
    expected_set,
    expected_guards,
    expected_params,
):
    connection = FakeUpdateConnection()
    original = _sensor_model_update()
    item = replace(
        original,
        values=replace(
            original.values,
            manufacturer=manufacturer,
            model=model,
        ),
        changes=changes,
    )

    result = update_metadata_item(
        connection,
        item,
        ApplyContext(),
    )

    assert result == ApplyItemResult(
        plan_id="updates.sensor_models[0]",
        resource_type="sensor_model",
        action=PlanAction.UPDATE,
        database_id=31,
    )
    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        f'UPDATE "sensor_models" SET {expected_set} '
        'WHERE "sensor_model_id" = %s '
        f'AND {expected_guards} '
        'RETURNING "sensor_model_id"'
    )
    assert params == expected_params


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
            "requires ResolvedSensorModelValues",
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
            "unsupported sensor_model UPDATE field",
        ),
        (
            {
                "changes": (
                    FieldChange("model", "M0", "M1"),
                    FieldChange("model", "M0", "M1"),
                ),
            },
            ValueError,
            "duplicate sensor_model UPDATE field",
        ),
        (
            {
                "changes": (
                    FieldChange("model", "M0", "Different model"),
                ),
            },
            ValueError,
            "change.after does not match resolved values",
        ),
    ],
)
def test_sensor_model_update_rejects_invalid_input_before_sql(
    overrides,
    error_type,
    message,
):
    connection = FakeUpdateConnection()
    item = replace(_sensor_model_update(), **overrides)

    with pytest.raises(error_type, match=message):
        update_metadata_item(
            connection,
            item,
            ApplyContext(),
        )

    assert connection.calls == []


def test_sensor_model_update_rejects_stale_plan():
    connection = FakeUpdateConnection(returned_row=None)

    with pytest.raises(ApplyError) as caught:
        update_metadata_item(
            connection,
            _sensor_model_update(),
            ApplyContext(),
        )

    assert caught.value.code == ApplyErrorCode.STALE_PLAN
    assert "sensor_model_id=31" in str(caught.value)
    assert len(connection.calls) == 1


@pytest.mark.parametrize("planned", [False, True])
def test_sensor_model_update_resolves_sensor_type(planned):
    connection = FakeUpdateConnection()
    context = ApplyContext()

    if planned:
        context.register(
            plan_id="sensor_types[0]",
            resource_type="sensor_type",
            database_id=3,
        )
        new_type = PlannedRef(
            resource_type="sensor_type",
            plan_id="sensor_types[0]",
        )
    else:
        new_type = ExistingRef(
            resource_type="sensor_type",
            database_id=3,
        )

    original = _sensor_model_update()
    item = replace(
        original,
        values=replace(
            original.values,
            sensor_type=new_type,
        ),
        changes=(
            FieldChange(
                field="sensor_type",
                before=ExistingRef("sensor_type", 2),
                after=new_type,
                identity_change=False,
            ),
        ),
    )

    result = update_metadata_item(
        connection,
        item,
        context,
    )

    assert result == ApplyItemResult(
        plan_id="updates.sensor_models[0]",
        resource_type="sensor_model",
        action=PlanAction.UPDATE,
        database_id=31,
    )
    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        'UPDATE "sensor_models" SET "sensor_type_id" = %s '
        'WHERE "sensor_model_id" = %s '
        'AND "sensor_type_id" IS NOT DISTINCT FROM %s '
        'RETURNING "sensor_model_id"'
    )
    assert params == (3, 31, 2)


def test_sensor_model_update_combines_scalar_and_relationship_changes():
    connection = FakeUpdateConnection()
    context = ApplyContext()

    context.register(
        plan_id="sensor_types[0]",
        resource_type="sensor_type",
        database_id=3,
    )

    new_type = PlannedRef(
        resource_type="sensor_type",
        plan_id="sensor_types[0]",
    )

    item = replace(
        _sensor_model_update(),
        values=ResolvedSensorModelValues(
            manufacturer="New manufacturer",
            model="M2",
            sensor_type=new_type,
        ),
        changes=(
            FieldChange(
                "manufacturer",
                "Old manufacturer",
                "New manufacturer",
                identity_change=True,
            ),
            FieldChange(
                "model",
                "M1",
                "M2",
                identity_change=True,
            ),
            FieldChange(
                "sensor_type",
                ExistingRef("sensor_type", 2),
                new_type,
                identity_change=False,
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
        'UPDATE "sensor_models" '
        'SET "manufacturer" = %s, "model" = %s, "sensor_type_id" = %s '
        'WHERE "sensor_model_id" = %s '
        'AND "manufacturer" IS NOT DISTINCT FROM %s '
        'AND "model" IS NOT DISTINCT FROM %s '
        'AND "sensor_type_id" IS NOT DISTINCT FROM %s '
        'RETURNING "sensor_model_id"'
    )
    assert params == (
        "New manufacturer",
        "M2",
        3,
        31,
        "Old manufacturer",
        "M1",
        2,
    )
    assert result.database_id == 31


@pytest.mark.parametrize(
    "registered_resource_type",
    [None, "site"],
)
def test_sensor_model_update_rejects_unavailable_planned_sensor_type(
    registered_resource_type,
):
    connection = FakeUpdateConnection()
    context = ApplyContext()

    if registered_resource_type is not None:
        context.register(
            plan_id="sensor_types[0]",
            resource_type=registered_resource_type,
            database_id=3,
        )

    new_type = PlannedRef(
        resource_type="sensor_type",
        plan_id="sensor_types[0]",
    )

    original = _sensor_model_update()
    item = replace(
        original,
        values=replace(
            original.values,
            sensor_type=new_type,
        ),
        changes=original.changes + (
            FieldChange(
                field="sensor_type",
                before=ExistingRef("sensor_type", 2),
                after=new_type,
                identity_change=False,
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

