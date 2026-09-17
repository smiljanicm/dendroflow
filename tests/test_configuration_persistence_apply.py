from dataclasses import replace

import pytest

from dendroflow import database
from dendroflow.configuration import persistence
from dendroflow.configuration.persistence import apply as apply_module
from dendroflow.configuration.persistence.context import ApplyContext
from dendroflow.configuration.persistence.models import (
    ApplyError,
    ApplyErrorCode,
    ApplyItemResult,
    ApplyResult,
    ApplyStageStatus,
    ApplyStatus,
)
from dendroflow.configuration.plan import (
    FieldChange,
    PlanAction,
    PlanError,
    PlanErrorCode,
    PlannedRef,
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSiteValues,
)


class FakeConnection:
    def __init__(
        self,
        rows=(),
        *,
        failure=None,
        failure_stage=None,
        failure_at=2,
        commit_failure=None,
    ):
        self.rows = iter(rows)
        self.failure = failure
        self.failure_stage = failure_stage
        self.failure_at = failure_at
        self.commit_failure = commit_failure
        self.calls = []
        self.events = []
        self.exit_error = None

    def __enter__(self):
        self.events.append("enter")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.exit_error = exc_value

        try:
            if exc_type is None:
                self.events.append("commit")
                if self.commit_failure is not None:
                    raise self.commit_failure
            else:
                self.events.append("rollback")
        finally:
            self.events.append("close")

        return False

    def execute(self, query, parameters):
        self.calls.append((query, parameters))
        self.events.append("execute")

        if (
            self.failure_stage == "execute"
            and len(self.calls) == self.failure_at
        ):
            raise self.failure

        return self

    def fetchone(self):
        self.events.append("fetchone")

        if (
            self.failure_stage == "fetchone"
            and len(self.calls) == self.failure_at
        ):
            raise self.failure

        return next(self.rows)


@pytest.fixture(autouse=True)
def forbid_database_connections(monkeypatch):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("test must supply a fake database connection")

    monkeypatch.setattr(database, "connect", unexpected_connection)


def install_connections(monkeypatch, *connections):
    remaining = iter(connections)
    calls = []

    def connect(name):
        calls.append(name)
        assert name == "dendroflow_metadata"
        return next(remaining)

    monkeypatch.setattr(database, "connect", connect)
    return calls


def site(plan_id, *, parent=None):
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="site",
        action=PlanAction.CREATE,
        values=ResolvedSiteValues(
            site_code=plan_id,
            name=plan_id,
            parent=parent,
        ),
    )


def parent_child_plan():
    parent = site("parent")
    child = site(
        "child",
        parent=PlannedRef("site", "parent"),
    )
    return ResolvedPlan(metadata_items=(child, parent))


def identity_update():
    return ResolvedPlanItem(
        plan_id="rename-site",
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


@pytest.mark.parametrize("reuse", [False, True])
def test_no_write_plan_does_not_connect(reuse):
    items = ()

    if reuse:
        items = tuple(
            replace(
                site(plan_id),
                action=PlanAction.REUSE,
                database_id=database_id,
            )
            for plan_id, database_id in (
                ("first", 11),
                ("second", 12),
            )
        )

    result = apply_module.apply_metadata_plan(
        ResolvedPlan(metadata_items=items)
    )

    assert result == ApplyResult(
        status=ApplyStatus.SUCCESS,
        metadata_status=ApplyStageStatus.NOT_REQUIRED,
        raw_status=ApplyStageStatus.NOT_REQUIRED,
        items=tuple(
            ApplyItemResult(
                plan_id=item.plan_id,
                resource_type=item.resource_type,
                action=item.action,
                database_id=item.database_id,
            )
            for item in items
        ),
    )


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("errors", ApplyErrorCode.PLAN_NOT_APPLICABLE),
        ("confirmation", ApplyErrorCode.CONFIRMATION_REQUIRED),
        ("raw", ApplyErrorCode.PLAN_NOT_APPLICABLE),
        ("cycle", ApplyErrorCode.PLAN_NOT_APPLICABLE),
    ],
)
def test_preparation_failure_happens_before_connecting(
    case,
    expected_code,
):
    if case == "errors":
        plan = ResolvedPlan(
            metadata_items=(site("new-site"),),
            errors=(
                PlanError(
                    code=PlanErrorCode.CONFLICT,
                    resource_type="site",
                    source_path="sites[0]",
                    message="Unresolved conflict",
                ),
            ),
        )
    elif case == "confirmation":
        plan = ResolvedPlan(
            metadata_items=(identity_update(),),
        )
    elif case == "raw":
        plan = ResolvedPlan(
            raw_items=(
                ResolvedPlanItem(
                    plan_id="raw-file",
                    resource_type="file",
                    action=PlanAction.REUSE,
                    database_id=1,
                    values=object(),
                ),
            ),
        )
    else:
        plan = ResolvedPlan(
            metadata_items=(
                site("first", parent=PlannedRef("site", "second")),
                site("second", parent=PlannedRef("site", "first")),
            ),
        )

    with pytest.raises(ApplyError) as caught:
        apply_module.apply_metadata_plan(plan)

    assert caught.value.code == expected_code


def test_confirmed_identity_update_is_committed(monkeypatch):
    connection = FakeConnection(rows=[(11,)])
    calls = install_connections(monkeypatch, connection)

    result = apply_module.apply_metadata_plan(
        ResolvedPlan(metadata_items=(identity_update(),)),
        confirm_identity_changes=True,
    )

    assert calls == ["dendroflow_metadata"]
    assert connection.events[-2:] == ["commit", "close"]
    assert result.status == ApplyStatus.SUCCESS
    assert result.metadata_status == ApplyStageStatus.COMMITTED
    assert result.raw_status == ApplyStageStatus.NOT_REQUIRED
    assert result.items == (
        ApplyItemResult(
            plan_id="rename-site",
            resource_type="site",
            action=PlanAction.UPDATE,
            database_id=11,
        ),
    )


def test_success_result_is_built_after_commit_and_close(monkeypatch):
    connection = FakeConnection(rows=[(101,), (102,)])
    calls = install_connections(monkeypatch, connection)

    def checked_result(**kwargs):
        assert connection.events[-2:] == ["commit", "close"]
        connection.events.append("result")
        return ApplyResult(**kwargs)

    monkeypatch.setattr(apply_module, "ApplyResult", checked_result)

    result = apply_module.apply_metadata_plan(parent_child_plan())

    assert calls == ["dendroflow_metadata"]
    assert connection.events.count("commit") == 1
    assert connection.events.count("close") == 1
    assert connection.events[-1] == "result"
    assert connection.calls[1][1][-1] == 101
    assert result.status == ApplyStatus.SUCCESS
    assert result.metadata_status == ApplyStageStatus.COMMITTED
    assert result.raw_status == ApplyStageStatus.NOT_REQUIRED
    assert [
        (item.plan_id, item.database_id)
        for item in result.items
    ] == [
        ("child", 102),
        ("parent", 101),
    ]


def test_connection_failure_propagates_without_retry(monkeypatch):
    failure = RuntimeError("connection failed")
    calls = []

    def connect(name):
        calls.append(name)
        raise failure

    monkeypatch.setattr(database, "connect", connect)

    with pytest.raises(RuntimeError) as caught:
        apply_module.apply_metadata_plan(parent_child_plan())

    assert caught.value is failure
    assert calls == ["dendroflow_metadata"]


@pytest.mark.parametrize("failure_stage", ["execute", "fetchone"])
def test_execution_failure_reaches_connection_exit(
    monkeypatch,
    failure_stage,
):
    failure = RuntimeError("write failed")
    connection = FakeConnection(
        rows=[(101,)],
        failure=failure,
        failure_stage=failure_stage,
    )
    calls = install_connections(monkeypatch, connection)

    with pytest.raises(RuntimeError) as caught:
        apply_module.apply_metadata_plan(parent_child_plan())

    assert caught.value is failure
    assert connection.exit_error is failure
    assert connection.events[-2:] == ["rollback", "close"]
    assert "commit" not in connection.events
    assert len(connection.calls) == 2
    assert calls == ["dendroflow_metadata"]


def test_stale_update_stops_execution_and_propagates(monkeypatch):
    parent_ref = PlannedRef("site", "parent")
    update = ResolvedPlanItem(
        plan_id="existing",
        resource_type="site",
        action=PlanAction.UPDATE,
        database_id=11,
        values=ResolvedSiteValues(
            site_code="existing",
            name="Existing site",
            parent=parent_ref,
        ),
        changes=(
            FieldChange(
                field="parent",
                before=None,
                after=parent_ref,
            ),
        ),
    )
    plan = ResolvedPlan(
        metadata_items=(
            update,
            site("parent"),
            site("later"),
        ),
    )
    connection = FakeConnection(rows=[(101,), None])
    calls = install_connections(monkeypatch, connection)

    with pytest.raises(ApplyError) as caught:
        apply_module.apply_metadata_plan(plan)

    assert caught.value.code == ApplyErrorCode.STALE_PLAN
    assert connection.exit_error is caught.value
    assert len(connection.calls) == 2
    assert connection.events[-2:] == ["rollback", "close"]
    assert "commit" not in connection.events
    assert calls == ["dendroflow_metadata"]


def test_commit_failure_does_not_build_success_result(monkeypatch):
    failure = RuntimeError("commit failed")
    connection = FakeConnection(
        rows=[(101,)],
        commit_failure=failure,
    )
    calls = install_connections(monkeypatch, connection)

    def unexpected_result(**kwargs):
        pytest.fail("must not build a result after commit failure")

    monkeypatch.setattr(apply_module, "ApplyResult", unexpected_result)

    with pytest.raises(RuntimeError) as caught:
        apply_module.apply_metadata_plan(
            ResolvedPlan(metadata_items=(site("new-site"),))
        )

    assert caught.value is failure
    assert connection.events[-2:] == ["commit", "close"]
    assert calls == ["dendroflow_metadata"]


@pytest.mark.parametrize("failure_stage", ["execute", "commit"])
def test_explicit_new_attempt_uses_fresh_context(
    monkeypatch,
    failure_stage,
):
    failure = RuntimeError("first attempt failed")
    first = FakeConnection(
        rows=[(101,), (102,)],
        failure=failure,
        failure_stage=(
            "execute" if failure_stage == "execute" else None
        ),
        commit_failure=(
            failure if failure_stage == "commit" else None
        ),
    )
    second = FakeConnection(rows=[(201,), (202,)])
    calls = install_connections(monkeypatch, first, second)
    contexts = []

    def fresh_context():
        context = ApplyContext()
        contexts.append(context)
        return context

    monkeypatch.setattr(apply_module, "ApplyContext", fresh_context)
    plan = parent_child_plan()

    with pytest.raises(RuntimeError) as caught:
        apply_module.apply_metadata_plan(plan)

    assert caught.value is failure
    assert calls == ["dendroflow_metadata"]

    result = apply_module.apply_metadata_plan(plan)

    assert calls == [
        "dendroflow_metadata",
        "dendroflow_metadata",
    ]
    assert len(contexts) == 2
    assert contexts[0] is not contexts[1]
    assert contexts[0].resolve(PlannedRef("site", "parent")) == 101
    assert contexts[1].resolve(PlannedRef("site", "parent")) == 201
    assert second.calls[1][1][-1] == 201
    assert [
        (item.plan_id, item.database_id)
        for item in result.items
    ] == [
        ("child", 202),
        ("parent", 201),
    ]
    assert result.metadata_status == ApplyStageStatus.COMMITTED


def test_public_api_exports_apply_metadata_plan():
    assert (
        persistence.apply_metadata_plan
        is apply_module.apply_metadata_plan
    )
