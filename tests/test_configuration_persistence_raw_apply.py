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
    ExistingRef,
    PlanAction,
    PlanError,
    PlanErrorCode,
    PlannedRef,
    ResolvedFileValues,
    ResolvedInterfaceValues,
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
        commit_failure=None,
    ):
        self.rows = iter(rows)
        self.failure = failure
        self.failure_stage = failure_stage
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

    def execute(self, query, params):
        self.calls.append((query, params))
        self.events.append("execute")

        if self.failure_stage == "execute" and len(self.calls) == 2:
            raise self.failure

        return self

    def fetchone(self):
        self.events.append("fetchone")

        if self.failure_stage == "fetchone" and len(self.calls) == 2:
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
        assert name == "dendroflow_raw"
        return next(remaining)

    monkeypatch.setattr(database, "connect", connect)
    return calls


def file_item():
    return ResolvedPlanItem(
        plan_id="file",
        resource_type="file",
        action=PlanAction.CREATE,
        values=ResolvedFileValues(
            filepath="/data/measurements.csv",
            timestamp_timezone="UTC",
            timestamp_format="%Y-%m-%d %H:%M:%S",
            reader_config={"reader": "csv", "options": {}},
        ),
    )


def interface_item():
    return ResolvedPlanItem(
        plan_id="interface",
        resource_type="interface",
        action=PlanAction.CREATE,
        values=ResolvedInterfaceValues(
            file=PlannedRef("file", "file"),
            deployment=ExistingRef("deployment", 91),
            values_column="water_level",
            timestamp_column="TIMESTAMP",
            unit="cm",
        ),
    )


def create_plan():
    return ResolvedPlan(
        raw_items=(interface_item(), file_item()),
    )


@pytest.mark.parametrize("reuse", [False, True])
def test_no_write_plan_does_not_connect(reuse):
    items = ()

    if reuse:
        interface = interface_item()
        items = (
            replace(
                interface,
                action=PlanAction.REUSE,
                database_id=101,
                values=replace(
                    interface.values,
                    file=ExistingRef("file", 17),
                ),
            ),
            replace(
                file_item(),
                action=PlanAction.REUSE,
                database_id=17,
            ),
        )

    result = apply_module.apply_raw_plan(
        ResolvedPlan(raw_items=items)
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
        ("metadata", ApplyErrorCode.PLAN_NOT_APPLICABLE),
        ("planned-deployment", ApplyErrorCode.PLAN_NOT_APPLICABLE),
        ("confirmation", ApplyErrorCode.CONFIRMATION_REQUIRED),
    ],
)
def test_preparation_failure_happens_before_connecting(
    case,
    expected_code,
):
    plan = create_plan()

    if case == "errors":
        plan = replace(
            plan,
            errors=(
                PlanError(
                    code=PlanErrorCode.CONFLICT,
                    resource_type="file",
                    source_path="files[0]",
                    message="Conflicting settings",
                ),
            ),
        )
    elif case == "metadata":
        plan = replace(
            plan,
            metadata_items=(
                ResolvedPlanItem(
                    plan_id="site",
                    resource_type="site",
                    action=PlanAction.CREATE,
                    values=ResolvedSiteValues(
                        site_code="TEST",
                        name="Test site",
                    ),
                ),
            ),
        )
    elif case == "planned-deployment":
        interface = interface_item()
        interface = replace(
            interface,
            values=replace(
                interface.values,
                deployment=PlannedRef("deployment", "deployment"),
            ),
        )
        plan = ResolvedPlan(
            raw_items=(interface, file_item()),
        )
    else:
        plan = ResolvedPlan(
            raw_items=(
                replace(file_item(), confirmation_required=True),
            ),
        )

    with pytest.raises(ApplyError) as caught:
        apply_module.apply_raw_plan(plan)

    assert caught.value.code == expected_code


def test_confirmation_is_forwarded_to_preparation(monkeypatch):
    connection = FakeConnection(rows=[(17,)])
    calls = install_connections(monkeypatch, connection)
    plan = ResolvedPlan(
        raw_items=(
            replace(file_item(), confirmation_required=True),
        ),
    )

    result = apply_module.apply_raw_plan(
        plan,
        confirm_identity_changes=True,
    )

    assert calls == ["dendroflow_raw"]
    assert connection.events[-2:] == ["commit", "close"]
    assert result.status == ApplyStatus.SUCCESS
    assert result.raw_status == ApplyStageStatus.COMMITTED
    assert result.metadata_status == ApplyStageStatus.NOT_REQUIRED


def test_success_result_is_built_after_commit_and_close(monkeypatch):
    connection = FakeConnection(rows=[(17,), (101,)])
    calls = install_connections(monkeypatch, connection)

    def checked_result(**kwargs):
        assert connection.events[-2:] == ["commit", "close"]
        connection.events.append("result")
        return ApplyResult(**kwargs)

    monkeypatch.setattr(apply_module, "ApplyResult", checked_result)

    result = apply_module.apply_raw_plan(create_plan())

    assert calls == ["dendroflow_raw"]
    assert connection.events.count("commit") == 1
    assert connection.events.count("close") == 1
    assert connection.events[-1] == "result"
    assert connection.calls[1][1][:2] == (17, 91)
    assert result.status == ApplyStatus.SUCCESS
    assert result.metadata_status == ApplyStageStatus.NOT_REQUIRED
    assert result.raw_status == ApplyStageStatus.COMMITTED
    assert [
        (item.plan_id, item.database_id)
        for item in result.items
    ] == [
        ("interface", 101),
        ("file", 17),
    ]


def test_connection_failure_propagates_without_retry(monkeypatch):
    failure = RuntimeError("connection failed")
    calls = []

    def connect(name):
        calls.append(name)
        raise failure

    monkeypatch.setattr(database, "connect", connect)

    with pytest.raises(RuntimeError) as caught:
        apply_module.apply_raw_plan(create_plan())

    assert caught.value is failure
    assert calls == ["dendroflow_raw"]


@pytest.mark.parametrize("failure_stage", ["execute", "fetchone"])
def test_execution_failure_reaches_connection_exit(
    monkeypatch,
    failure_stage,
):
    failure = RuntimeError("interface write failed")
    connection = FakeConnection(
        rows=[(17,)],
        failure=failure,
        failure_stage=failure_stage,
    )
    calls = install_connections(monkeypatch, connection)

    with pytest.raises(RuntimeError) as caught:
        apply_module.apply_raw_plan(create_plan())

    assert caught.value is failure
    assert connection.exit_error is failure
    assert connection.events[-2:] == ["rollback", "close"]
    assert "commit" not in connection.events
    assert len(connection.calls) == 2
    assert calls == ["dendroflow_raw"]


def test_commit_failure_does_not_build_success_result(monkeypatch):
    failure = RuntimeError("commit failed")
    connection = FakeConnection(
        rows=[(17,), (101,)],
        commit_failure=failure,
    )
    calls = install_connections(monkeypatch, connection)

    def unexpected_result(**kwargs):
        pytest.fail("must not build a result after commit failure")

    monkeypatch.setattr(apply_module, "ApplyResult", unexpected_result)

    with pytest.raises(RuntimeError) as caught:
        apply_module.apply_raw_plan(create_plan())

    assert caught.value is failure
    assert connection.events[-2:] == ["commit", "close"]
    assert calls == ["dendroflow_raw"]


@pytest.mark.parametrize("failure_stage", ["execute", "commit"])
def test_explicit_new_attempt_uses_fresh_context(
    monkeypatch,
    failure_stage,
):
    failure = RuntimeError("first attempt failed")
    first = FakeConnection(
        rows=[(17,), (101,)],
        failure=failure,
        failure_stage=(
            "execute" if failure_stage == "execute" else None
        ),
        commit_failure=(
            failure if failure_stage == "commit" else None
        ),
    )
    second = FakeConnection(rows=[(27,), (201,)])
    calls = install_connections(monkeypatch, first, second)
    contexts = []

    def fresh_context():
        context = ApplyContext()
        contexts.append(context)
        return context

    monkeypatch.setattr(apply_module, "ApplyContext", fresh_context)
    plan = create_plan()

    with pytest.raises(RuntimeError) as caught:
        apply_module.apply_raw_plan(plan)

    assert caught.value is failure
    assert calls == ["dendroflow_raw"]

    result = apply_module.apply_raw_plan(plan)

    assert calls == ["dendroflow_raw", "dendroflow_raw"]
    assert len(contexts) == 2
    assert contexts[0] is not contexts[1]
    assert contexts[0].resolve(PlannedRef("file", "file")) == 17
    assert contexts[1].resolve(PlannedRef("file", "file")) == 27
    assert second.calls[1][1][:2] == (27, 91)
    assert [
        (item.plan_id, item.database_id)
        for item in result.items
    ] == [
        ("interface", 201),
        ("file", 27),
    ]
    assert result.raw_status == ApplyStageStatus.COMMITTED


def test_public_api_exports_apply_raw_plan():
    assert persistence.apply_raw_plan is apply_module.apply_raw_plan

