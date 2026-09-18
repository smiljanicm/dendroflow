import pytest

from dendroflow import database
from dendroflow.configuration.persistence.context import ApplyContext
from dendroflow.configuration.persistence.models import (
    ApplyError,
    ApplyErrorCode,
    ApplyItemResult,
    ApplyStageStatus,
)
from dendroflow.configuration.persistence.raw_execution import (
    execute_raw_preparation,
)
from dendroflow.configuration.persistence.raw_preparation import (
    prepare_raw_plan,
)
from dendroflow.configuration.persistence.transactions import (
    StageTransactionError,
    run_write_stage,
)
from dendroflow.configuration.plan import (
    PlanAction,
    ResolvedFileValues,
    ResolvedPlan,
    ResolvedPlanItem,
)


class FakeConnection:
    def __init__(
        self,
        *,
        commit_error=None,
        rollback_error=None,
        close_error=None,
    ):
        self.commit_error = commit_error
        self.rollback_error = rollback_error
        self.close_error = close_error
        self.events = []
        self.calls = []

    def commit(self):
        self.events.append("commit")
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self):
        self.events.append("rollback")
        if self.rollback_error is not None:
            raise self.rollback_error

    def close(self):
        self.events.append("close")
        if self.close_error is not None:
            raise self.close_error

    def execute(self, query, params):
        self.events.append("execute")
        self.calls.append((query, params))
        return self

    def fetchone(self):
        self.events.append("fetchone")
        return (17,)


@pytest.fixture(autouse=True)
def forbid_database_connections(monkeypatch):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("test must supply a fake database connection")

    monkeypatch.setattr(database, "connect", unexpected_connection)


def install_connection(monkeypatch, connection):
    calls = []

    def connect(name):
        calls.append(name)
        return connection

    monkeypatch.setattr(database, "connect", connect)
    return calls


def item_results():
    return (
        ApplyItemResult(
            plan_id="file",
            resource_type="file",
            action=PlanAction.CREATE,
            database_id=17,
        ),
    )


@pytest.mark.parametrize(
    "database_name",
    ["dendroflow_metadata", "dendroflow_raw"],
)
def test_stage_commits_then_closes_before_returning(
    monkeypatch,
    database_name,
):
    connection = FakeConnection()
    calls = install_connection(monkeypatch, connection)
    expected = item_results()

    def execute(received):
        assert received is connection
        connection.events.append("work")
        return expected

    result = run_write_stage(database_name, execute)

    assert result is expected
    assert calls == [database_name]
    assert connection.events == ["work", "commit", "close"]


def test_connection_failure_does_not_execute_or_retry(monkeypatch):
    failure = RuntimeError("connection failed")
    calls = []

    def connect(name):
        calls.append(name)
        raise failure

    def execute(connection):
        pytest.fail("execution must not start")

    monkeypatch.setattr(database, "connect", connect)

    with pytest.raises(StageTransactionError) as caught:
        run_write_stage("dendroflow_raw", execute)

    assert calls == ["dendroflow_raw"]
    assert caught.value.status == ApplyStageStatus.FAILED
    assert caught.value.items == ()
    assert caught.value.__cause__ is failure
    assert caught.value.rollback_error is None
    assert caught.value.close_error is None


@pytest.mark.parametrize("failure_phase", ["execution", "commit"])
@pytest.mark.parametrize("rollback_fails", [False, True])
@pytest.mark.parametrize("close_fails", [False, True])
def test_failure_retains_primary_and_cleanup_errors(
    monkeypatch,
    failure_phase,
    rollback_fails,
    close_fails,
):
    primary = ApplyError(
        ApplyErrorCode.STALE_PLAN,
        "guarded operation failed",
    ) if failure_phase == "execution" else RuntimeError("commit failed")

    rollback_error = (
        RuntimeError("rollback failed")
        if rollback_fails
        else None
    )
    close_error = (
        RuntimeError("close failed")
        if close_fails
        else None
    )
    connection = FakeConnection(
        commit_error=primary if failure_phase == "commit" else None,
        rollback_error=rollback_error,
        close_error=close_error,
    )
    calls = install_connection(monkeypatch, connection)

    def execute(received):
        assert received is connection
        connection.events.append("work")

        if failure_phase == "execution":
            raise primary

        return item_results()

    with pytest.raises(StageTransactionError) as caught:
        run_write_stage("dendroflow_raw", execute)

    expected_status = (
        ApplyStageStatus.UNKNOWN
        if failure_phase == "commit" or rollback_fails
        else ApplyStageStatus.FAILED
    )

    assert caught.value.status == expected_status
    assert caught.value.items == ()
    assert caught.value.__cause__ is primary
    assert caught.value.rollback_error is rollback_error
    assert caught.value.close_error is close_error
    assert calls == ["dendroflow_raw"]

    expected_events = ["work"]
    if failure_phase == "commit":
        expected_events.append("commit")
    expected_events.extend(["rollback", "close"])

    assert connection.events == expected_events

    if isinstance(primary, ApplyError):
        assert primary.code == ApplyErrorCode.STALE_PLAN


def test_close_failure_preserves_acknowledged_commit_and_items(monkeypatch):
    failure = RuntimeError("close failed")
    connection = FakeConnection(close_error=failure)
    calls = install_connection(monkeypatch, connection)
    expected = item_results()

    def execute(received):
        assert received is connection
        connection.events.append("work")
        return expected

    with pytest.raises(StageTransactionError) as caught:
        run_write_stage("dendroflow_raw", execute)

    assert caught.value.status == ApplyStageStatus.COMMITTED
    assert caught.value.items is expected
    assert caught.value.__cause__ is failure
    assert caught.value.rollback_error is None
    assert caught.value.close_error is failure
    assert calls == ["dendroflow_raw"]
    assert connection.events == ["work", "commit", "close"]


@pytest.mark.parametrize("phase", ["execution", "commit"])
def test_keyboard_interrupt_propagates_and_attempts_close(monkeypatch, phase):
    interruption = KeyboardInterrupt()
    connection = FakeConnection(
        commit_error=interruption if phase == "commit" else None,
        close_error=RuntimeError("close also failed"),
    )
    calls = install_connection(monkeypatch, connection)

    def execute(received):
        assert received is connection
        connection.events.append("work")

        if phase == "execution":
            raise interruption

        return item_results()

    with pytest.raises(KeyboardInterrupt) as caught:
        run_write_stage("dendroflow_raw", execute)

    assert caught.value is interruption
    assert calls == ["dendroflow_raw"]
    assert connection.events == (
        ["work", "close"]
        if phase == "execution"
        else ["work", "commit", "close"]
    )


def test_real_raw_executor_runs_inside_owned_transaction(monkeypatch):
    item = ResolvedPlanItem(
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
    prepared = prepare_raw_plan(
        ResolvedPlan(raw_items=(item,))
    )
    context = ApplyContext()
    connection = FakeConnection()
    calls = install_connection(monkeypatch, connection)

    result = run_write_stage(
        "dendroflow_raw",
        lambda owned_connection: execute_raw_preparation(
            owned_connection,
            prepared,
            context,
        ),
    )

    assert result == item_results()
    assert calls == ["dendroflow_raw"]
    assert len(connection.calls) == 1
    assert connection.events == [
        "execute",
        "fetchone",
        "commit",
        "close",
    ]

