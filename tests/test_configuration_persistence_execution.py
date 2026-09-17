from dataclasses import replace

import pytest

from dendroflow import database
from dendroflow.configuration.persistence.context import ApplyContext
from dendroflow.configuration.persistence.execution import (
    execute_metadata_preparation,
)
from dendroflow.configuration.persistence.models import (
    ApplyError,
    ApplyErrorCode,
    ApplyItemResult,
)
from dendroflow.configuration.persistence.preparation import (
    prepare_metadata_plan,
)
from dendroflow.configuration.plan import (
    FieldChange,
    PlanAction,
    PlannedRef,
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSiteValues,
)


@pytest.fixture(autouse=True)
def forbid_database_connections(monkeypatch):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("executor must use the supplied connection")

    monkeypatch.setattr(database, "connect", unexpected_connection)


class FakeConnection:
    def __init__(
        self,
        rows=(),
        *,
        failure=None,
        failure_at=None,
        failure_stage="execute",
    ):
        self.rows = iter(rows)
        self.failure = failure
        self.failure_at = failure_at
        self.failure_stage = failure_stage
        self.calls = []
        self.fetch_calls = 0

    def execute(self, query, params):
        self.calls.append((query, params))

        if (
            len(self.calls) == self.failure_at
            and self.failure_stage == "execute"
        ):
            raise self.failure

        return self

    def fetchone(self):
        self.fetch_calls += 1

        if (
            len(self.calls) == self.failure_at
            and self.failure_stage == "fetchone"
        ):
            raise self.failure

        return next(self.rows)


def _create(plan_id, *, site_code=None, parent=None):
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="site",
        action=PlanAction.CREATE,
        values=ResolvedSiteValues(
            site_code=plan_id if site_code is None else site_code,
            name=plan_id,
            parent=parent,
        ),
    )


def _parent_update(parent):
    return ResolvedPlanItem(
        plan_id="updated",
        resource_type="site",
        action=PlanAction.UPDATE,
        database_id=11,
        values=ResolvedSiteValues(
            site_code="CHILD",
            name="Existing child",
            parent=parent,
        ),
        changes=(
            FieldChange(
                field="parent",
                before=None,
                after=parent,
            ),
        ),
    )


def _prepare(*items):
    return prepare_metadata_plan(
        ResolvedPlan(metadata_items=items),
        confirm_identity_changes=True,
    )


def _result(item, database_id):
    return ApplyItemResult(
        plan_id=item.plan_id,
        resource_type=item.resource_type,
        action=item.action,
        database_id=database_id,
    )


def _sql(query):
    text = query if isinstance(query, str) else query.as_string()
    return " ".join(text.split())


def test_metadata_execution_accepts_empty_preparation():
    connection = FakeConnection()

    results = execute_metadata_preparation(
        connection,
        _prepare(),
        ApplyContext(),
    )

    assert results == ()
    assert connection.calls == []
    assert connection.fetch_calls == 0


def test_metadata_execution_reuse_only_issues_no_sql():
    first = replace(
        _create("first"),
        action=PlanAction.REUSE,
        database_id=11,
    )
    second = replace(
        _create("second"),
        action=PlanAction.REUSE,
        database_id=12,
    )
    connection = FakeConnection()
    context = ApplyContext()

    results = execute_metadata_preparation(
        connection,
        _prepare(first, second),
        context,
    )

    assert results == (
        _result(first, 11),
        _result(second, 12),
    )
    assert connection.calls == []
    assert connection.fetch_calls == 0

    with pytest.raises(ApplyError) as caught:
        context.resolve(PlannedRef("site", "first"))

    assert caught.value.code == ApplyErrorCode.UNRESOLVED_PLANNED_REF


def test_metadata_execution_mixes_actions_and_preserves_result_order():
    parent = _create("parent")
    parent_ref = PlannedRef("site", "parent")
    updated = _parent_update(parent_ref)
    reused = replace(
        updated,
        plan_id="reused",
        action=PlanAction.REUSE,
        values=replace(updated.values, parent=None),
        changes=(),
    )

    prepared = _prepare(updated, reused, parent)
    assert prepared.execution_items == (reused, parent, updated)

    connection = FakeConnection(rows=[(101,), (11,)])
    context = ApplyContext()

    results = execute_metadata_preparation(
        connection,
        prepared,
        context,
    )

    assert results == (
        _result(updated, 11),
        _result(reused, 11),
        _result(parent, 101),
    )
    assert len(connection.calls) == 2
    assert connection.fetch_calls == 2

    create_query, create_params = connection.calls[0]
    update_query, update_params = connection.calls[1]

    assert _sql(create_query).startswith("INSERT INTO sites")
    assert create_params == ("parent", "parent", None, None, None, None)

    assert _sql(update_query).startswith('UPDATE "sites"')
    assert update_params == (101, 11, None)
    assert context.resolve(parent_ref) == 101


def test_metadata_execution_shares_created_ids_between_create_writers():
    parent = _create("parent")
    parent_ref = PlannedRef("site", "parent")
    child = _create("child", parent=parent_ref)

    connection = FakeConnection(rows=[(101,), (102,)])
    context = ApplyContext()

    results = execute_metadata_preparation(
        connection,
        _prepare(child, parent),
        context,
    )

    assert results == (
        _result(child, 102),
        _result(parent, 101),
    )
    assert len(connection.calls) == 2

    _, parent_params = connection.calls[0]
    _, child_params = connection.calls[1]

    assert parent_params == ("parent", "parent", None, None, None, None)
    assert child_params == ("child", "child", None, None, None, 101)
    assert context.resolve(parent_ref) == 101
    assert context.resolve(PlannedRef("site", "child")) == 102


@pytest.mark.parametrize("failure_at", [1, 2])
@pytest.mark.parametrize("failure_stage", ["execute", "fetchone"])
def test_metadata_execution_stops_and_preserves_failure(
    failure_at,
    failure_stage,
):
    items = (
        _create("first"),
        _create("second"),
        _create("third"),
    )
    failure = RuntimeError("database operation failed")
    connection = FakeConnection(
        rows=[(101,), (102,), (103,)],
        failure=failure,
        failure_at=failure_at,
        failure_stage=failure_stage,
    )
    context = ApplyContext()

    with pytest.raises(RuntimeError) as caught:
        execute_metadata_preparation(
            connection,
            _prepare(*items),
            context,
        )

    assert caught.value is failure
    assert len(connection.calls) == failure_at
    assert connection.fetch_calls == (
        failure_at
        if failure_stage == "fetchone"
        else failure_at - 1
    )

    with pytest.raises(ApplyError) as unresolved:
        context.resolve(PlannedRef("site", "third"))

    assert (
        unresolved.value.code
        == ApplyErrorCode.UNRESOLVED_PLANNED_REF
    )

    if failure_at == 2:
        assert context.resolve(PlannedRef("site", "first")) == 101


def test_metadata_execution_propagates_stale_update_after_create():
    parent = _create("parent")
    parent_ref = PlannedRef("site", "parent")
    updated = _parent_update(parent_ref)
    later = _create("later")

    connection = FakeConnection(rows=[(101,), None])
    context = ApplyContext()

    with pytest.raises(ApplyError) as caught:
        execute_metadata_preparation(
            connection,
            _prepare(updated, parent, later),
            context,
        )

    assert caught.value.code == ApplyErrorCode.STALE_PLAN
    assert len(connection.calls) == 2
    assert context.resolve(parent_ref) == 101

    with pytest.raises(ApplyError) as unresolved:
        context.resolve(PlannedRef("site", "later"))

    assert (
        unresolved.value.code
        == ApplyErrorCode.UNRESOLVED_PLANNED_REF
    )


def test_metadata_execution_updates_before_create_reusing_unique_key():
    renamed = ResolvedPlanItem(
        plan_id="renamed",
        resource_type="site",
        action=PlanAction.UPDATE,
        database_id=11,
        values=ResolvedSiteValues(
            site_code="NEW",
            name="Existing site",
        ),
        changes=(
            FieldChange(
                field="site_code",
                before="OLD",
                after="NEW",
                identity_change=True,
            ),
        ),
    )
    created = _create("created", site_code="OLD")

    connection = FakeConnection(rows=[(11,), (101,)])
    context = ApplyContext()

    results = execute_metadata_preparation(
        connection,
        _prepare(created, renamed),
        context,
    )

    assert results == (
        _result(created, 101),
        _result(renamed, 11),
    )
    assert len(connection.calls) == 2

    update_query, update_params = connection.calls[0]
    create_query, create_params = connection.calls[1]

    assert _sql(update_query).startswith('UPDATE "sites"')
    assert update_params == ("NEW", 11, "OLD")
    assert _sql(create_query).startswith("INSERT INTO sites")
    assert create_params == ("created", "OLD", None, None, None, None)

    assert context.resolve(PlannedRef("site", "created")) == 101

    with pytest.raises(ApplyError) as unresolved:
        context.resolve(PlannedRef("site", "renamed"))

    assert (
        unresolved.value.code
        == ApplyErrorCode.UNRESOLVED_PLANNED_REF
    )
