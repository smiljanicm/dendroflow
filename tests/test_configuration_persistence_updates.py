from dataclasses import replace

import pytest

from dendroflow.configuration.persistence.context import ApplyContext
from dendroflow.configuration.persistence.models import (
    ApplyError,
    ApplyErrorCode,
    ApplyItemResult,
)
from dendroflow.configuration.persistence.updates import (
    _validate_site_update,
    update_metadata_item,
)
from dendroflow.configuration.plan import (
    ExistingRef,
    FieldChange,
    PlanAction,
    PlannedRef,
    ResolvedPlanItem,
    ResolvedSiteValues,
)


def _site_update() -> ResolvedPlanItem:
    return ResolvedPlanItem(
        plan_id="updates.sites[0]",
        resource_type="site",
        action=PlanAction.UPDATE,
        database_id=11,
        values=ResolvedSiteValues(
            site_code="SITE_A",
            name="New name",
        ),
        changes=(
            FieldChange(
                field="name",
                before="Old name",
                after="New name",
            ),
        ),
    )


def test_site_update_validation_accepts_consistent_item():
    item = _site_update()

    assert _validate_site_update(item) is item.values


@pytest.mark.parametrize(
    ("action", "database_id"),
    [
        (PlanAction.CREATE, None),
        (PlanAction.REUSE, 11),
    ],
)
def test_site_update_validation_rejects_other_actions(
    action,
    database_id,
):
    item = replace(
        _site_update(),
        action=action,
        database_id=database_id,
        changes=(),
    )

    with pytest.raises(ValueError, match="requires UPDATE action"):
        _validate_site_update(item)


def test_site_update_validation_rejects_unsupported_resource():
    item = replace(
        _site_update(),
        resource_type="file",
    )

    with pytest.raises(
        ValueError,
        match="unsupported METADATA update resource type",
    ):
        _validate_site_update(item)


def test_site_update_validation_rejects_wrong_values_type():
    item = replace(
        _site_update(),
        values=object(),
    )

    with pytest.raises(
        TypeError,
        match="requires ResolvedSiteValues",
    ):
        _validate_site_update(item)


@pytest.mark.parametrize("database_id", [0, -1, True, 1.5, "11"])
def test_site_update_validation_rejects_invalid_database_id(
    database_id,
):
    item = replace(
        _site_update(),
        database_id=database_id,
    )

    with pytest.raises(
        ValueError,
        match="positive integer database_id",
    ):
        _validate_site_update(item)


def test_update_plan_item_rejects_missing_database_id():
    with pytest.raises(
        ValueError,
        match="must have database_id",
    ):
        replace(_site_update(), database_id=None)


def test_update_plan_item_rejects_empty_changes():
    with pytest.raises(
        ValueError,
        match="must contain at least one change",
    ):
        replace(_site_update(), changes=())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            (FieldChange("unknown", None, "value"),),
            "unsupported site UPDATE field",
        ),
        (
            (
                FieldChange("name", "Old name", "New name"),
                FieldChange("name", "Old name", "New name"),
            ),
            "duplicate site UPDATE field",
        ),
        (
            (FieldChange("name", "Old name", "Different name"),),
            "change.after does not match resolved values",
        ),
    ],
)
def test_site_update_validation_rejects_malformed_changes(
    changes,
    message,
):
    item = replace(
        _site_update(),
        changes=changes,
    )

    with pytest.raises(ValueError, match=message):
        _validate_site_update(item)


class FakeUpdateConnection:
    def __init__(self, returned_row=(11,)):
        self.returned_row = returned_row
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))
        return self

    def fetchone(self):
        return self.returned_row


def test_site_update_persists_name_with_old_value_guard():
    connection = FakeUpdateConnection()
    item = _site_update()

    result = update_metadata_item(
        connection,
        item,
        ApplyContext(),
    )

    assert result == ApplyItemResult(
        plan_id="updates.sites[0]",
        resource_type="site",
        action=PlanAction.UPDATE,
        database_id=11,
    )
    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert " ".join(query.as_string().split()) == (
        'UPDATE "sites" SET "name" = %s '
        'WHERE "site_id" = %s '
        'AND "name" IS NOT DISTINCT FROM %s '
        'RETURNING "site_id"'
    )
    assert params == ("New name", 11, "Old name")


def test_site_update_writes_and_guards_each_changed_field():
    connection = FakeUpdateConnection()
    item = replace(
        _site_update(),
        values=ResolvedSiteValues(
            site_code="SITE_B",
            name="New name",
            description="Untouched description",
        ),
        changes=(
            FieldChange(
                field="name",
                before="Old name",
                after="New name",
            ),
            FieldChange(
                field="site_code",
                before="SITE_A",
                after="SITE_B",
                identity_change=True,
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
        'UPDATE "sites" SET "name" = %s, "site_code" = %s '
        'WHERE "site_id" = %s '
        'AND "name" IS NOT DISTINCT FROM %s '
        'AND "site_code" IS NOT DISTINCT FROM %s '
        'RETURNING "site_id"'
    )
    assert params == (
        "New name",
        "SITE_B",
        11,
        "Old name",
        "SITE_A",
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (None, "New description"),
        ("Old description", None),
    ],
)
def test_site_update_handles_nullable_description(before, after):
    connection = FakeUpdateConnection()
    item = replace(
        _site_update(),
        values=ResolvedSiteValues(
            site_code="SITE_A",
            name="Existing site",
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

    update_metadata_item(
        connection,
        item,
        ApplyContext(),
    )

    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert (
        '"description" IS NOT DISTINCT FROM %s'
        in query.as_string()
    )
    assert params == (after, 11, before)


def test_site_update_rejects_stale_plan():
    connection = FakeUpdateConnection(returned_row=None)

    with pytest.raises(ApplyError) as caught:
        update_metadata_item(
            connection,
            _site_update(),
            ApplyContext(),
        )

    assert caught.value.code == ApplyErrorCode.STALE_PLAN
    assert len(connection.calls) == 1


@pytest.mark.parametrize(
    ("before", "after", "expected_params"),
    [
        (
            None,
            ExistingRef("site", 5),
            (5, 11, None),
        ),
        (
            ExistingRef("site", 5),
            ExistingRef("site", 6),
            (6, 11, 5),
        ),
        (
            ExistingRef("site", 5),
            None,
            (None, 11, 5),
        ),
    ],
)
def test_site_update_resolves_existing_parent_changes(
    before,
    after,
    expected_params,
):
    connection = FakeUpdateConnection()
    item = replace(
        _site_update(),
        values=ResolvedSiteValues(
            site_code="SITE_A",
            name="Existing site",
            parent=after,
        ),
        changes=(
            FieldChange(
                field="parent",
                before=before,
                after=after,
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
        'UPDATE "sites" SET "parent_id" = %s '
        'WHERE "site_id" = %s '
        'AND "parent_id" IS NOT DISTINCT FROM %s '
        'RETURNING "site_id"'
    )
    assert params == expected_params


def test_site_update_resolves_planned_parent():
    connection = FakeUpdateConnection()
    context = ApplyContext()

    context.register(
        plan_id="sites[0]",
        resource_type="site",
        database_id=6,
    )

    parent = PlannedRef(
        resource_type="site",
        plan_id="sites[0]",
    )

    item = replace(
        _site_update(),
        values=ResolvedSiteValues(
            site_code="SITE_A",
            name="Existing site",
            parent=parent,
        ),
        changes=(
            FieldChange(
                field="parent",
                before=ExistingRef("site", 5),
                after=parent,
            ),
        ),
    )

    result = update_metadata_item(
        connection,
        item,
        context,
    )

    assert len(connection.calls) == 1

    _, params = connection.calls[0]

    assert params == (6, 11, 5)
    assert result.database_id == 11
    assert result.action == PlanAction.UPDATE
    assert context.resolve(parent) == 6


def test_site_update_rejects_unresolved_planned_parent():
    connection = FakeUpdateConnection()

    parent = PlannedRef(
        resource_type="site",
        plan_id="sites[0]",
    )

    item = replace(
        _site_update(),
        values=ResolvedSiteValues(
            site_code="SITE_A",
            name="Existing site",
            parent=parent,
        ),
        changes=(
            FieldChange(
                field="parent",
                before=ExistingRef("site", 5),
                after=parent,
            ),
        ),
    )

    with pytest.raises(ApplyError) as caught:
        update_metadata_item(
            connection,
            item,
            ApplyContext(),
        )

    assert caught.value.code == ApplyErrorCode.UNRESOLVED_PLANNED_REF
    assert connection.calls == []


def test_site_update_propagates_database_failure():
    failure = RuntimeError("database unavailable")

    class FailingConnection:
        def __init__(self):
            self.calls = []

        def execute(self, query, params):
            self.calls.append((query, params))
            raise failure

    connection = FailingConnection()

    with pytest.raises(RuntimeError) as caught:
        update_metadata_item(
            connection,
            _site_update(),
            ApplyContext(),
        )

    assert caught.value is failure
    assert len(connection.calls) == 1


@pytest.mark.parametrize(
    "returned_row",
    [
        (),
        (12,),
        (0,),
        (-1,),
        (True,),
        ("11",),
        (11.0,),
        (11, 12),
    ],
)
def test_site_update_rejects_unexpected_returned_id(
    returned_row,
):
    connection = FakeUpdateConnection(
        returned_row=returned_row,
    )

    with pytest.raises(
        ValueError,
        match="unexpected database_id",
    ):
        update_metadata_item(
            connection,
            _site_update(),
            ApplyContext(),
        )

    assert len(connection.calls) == 1


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
            {"resource_type": "file"},
            ValueError,
            "unsupported METADATA update resource type",
        ),
        (
            {"values": object()},
            TypeError,
            "requires ResolvedSiteValues",
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
            "unsupported site UPDATE field",
        ),
        (
            {
                "changes": (
                    FieldChange("name", "Old name", "New name"),
                    FieldChange("name", "Old name", "New name"),
                ),
            },
            ValueError,
            "duplicate site UPDATE field",
        ),
        (
            {
                "changes": (
                    FieldChange("name", "Old name", "Different name"),
                ),
            },
            ValueError,
            "change.after does not match resolved values",
        ),
    ],
)
def test_metadata_update_rejects_invalid_input_before_sql(
    overrides,
    error_type,
    message,
):
    connection = FakeUpdateConnection()
    item = replace(_site_update(), **overrides)

    with pytest.raises(error_type, match=message):
        update_metadata_item(
            connection,
            item,
            ApplyContext(),
        )

    assert connection.calls == []


