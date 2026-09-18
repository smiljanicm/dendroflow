from dataclasses import replace
from datetime import datetime, timezone

import pytest

from dendroflow import database
from dendroflow.configuration import persistence
from dendroflow.configuration.persistence import combined_apply as apply_module
from dendroflow.configuration.persistence.context import ApplyContext
from dendroflow.configuration.persistence.models import (
    ApplyError,
    ApplyErrorCode,
    ApplyExecutionError,
    ApplyItemResult,
    ApplyStageStatus,
    ApplyStatus,
)
from dendroflow.configuration.persistence.transactions import (
    StageTransactionError,
)
from dendroflow.configuration.plan import (
    ExistingRef,
    PlanAction,
    PlannedRef,
    ResolvedDeploymentValues,
    ResolvedFileValues,
    ResolvedInterfaceValues,
    ResolvedPlan,
    ResolvedPlanItem,
)

METADATA = "dendroflow_metadata"
RAW = "dendroflow_raw"


class FakeConnection:
    def __init__(
        self,
        name,
        events,
        rows,
        *,
        failure_phase=None,
        fail_at=1,
    ):
        self.name = name
        self.events = events
        self.rows = iter(rows)
        self.failure_phase = failure_phase
        self.fail_at = fail_at
        self.failure = RuntimeError(f"{name}: {failure_phase}")
        self.rollback_error = RuntimeError("rollback failed")
        self.calls = []

    def execute(self, query, params):
        self.events.append((self.name, "execute"))
        self.calls.append((query, params))

        if (
            self.failure_phase in {"execution", "rollback"}
            and len(self.calls) == self.fail_at
        ):
            raise self.failure

        return self

    def fetchone(self):
        return next(self.rows)

    def commit(self):
        self.events.append((self.name, "commit"))
        if self.failure_phase == "commit":
            raise self.failure

    def rollback(self):
        self.events.append((self.name, "rollback"))
        if self.failure_phase == "rollback":
            raise self.rollback_error

    def close(self):
        self.events.append((self.name, "close"))
        if self.failure_phase == "close":
            raise self.failure


@pytest.fixture(autouse=True)
def forbid_database_connections(monkeypatch):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("test must supply fake database connections")

    monkeypatch.setattr(database, "connect", unexpected_connection)


def install_connections(monkeypatch, events, *entries):
    remaining = iter(entries)

    def connect(name):
        events.append((name, "connect"))
        expected_name, value = next(remaining)
        assert name == expected_name

        if isinstance(value, Exception):
            raise value

        return value

    monkeypatch.setattr(database, "connect", connect)


def deployment_item():
    return ResolvedPlanItem(
        plan_id="deployment",
        resource_type="deployment",
        action=PlanAction.CREATE,
        values=ResolvedDeploymentValues(
            sensor=ExistingRef("sensor", 1),
            location=ExistingRef("location", 2),
            variable=ExistingRef("variable", 3),
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            valid_to=None,
        ),
    )


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


def interface_item(*, existing_deployment=False):
    return ResolvedPlanItem(
        plan_id="interface",
        resource_type="interface",
        action=PlanAction.CREATE,
        values=ResolvedInterfaceValues(
            file=PlannedRef("file", "file"),
            deployment=(
                ExistingRef("deployment", 91)
                if existing_deployment
                else PlannedRef("deployment", "deployment")
            ),
            values_column="value",
            timestamp_column="TIMESTAMP",
            unit="cm",
        ),
    )


def combined_plan():
    return ResolvedPlan(
        metadata_items=(deployment_item(),),
        raw_items=(interface_item(), file_item()),
    )


def single_stage_plan(stage):
    if stage == METADATA:
        return ResolvedPlan(metadata_items=(deployment_item(),))

    return ResolvedPlan(
        raw_items=(
            interface_item(existing_deployment=True),
            file_item(),
        ),
    )


def reuse_plan():
    interface = interface_item(existing_deployment=True)

    return ResolvedPlan(
        metadata_items=(
            replace(
                deployment_item(),
                action=PlanAction.REUSE,
                database_id=91,
            ),
        ),
        raw_items=(
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
        ),
    )


def identities(result):
    return [
        (item.plan_id, item.database_id)
        for item in result.items
    ]


@pytest.mark.parametrize("reuse", [False, True])
def test_no_write_plan_does_not_connect(reuse):
    plan = reuse_plan() if reuse else ResolvedPlan()

    result = apply_module.apply_plan(plan)

    assert result.status == ApplyStatus.SUCCESS
    assert result.metadata_status == ApplyStageStatus.NOT_REQUIRED
    assert result.raw_status == ApplyStageStatus.NOT_REQUIRED
    assert identities(result) == (
        [("deployment", 91), ("interface", 101), ("file", 17)]
        if reuse
        else []
    )


@pytest.mark.parametrize("stage", [METADATA, RAW])
def test_single_stage_plan_opens_only_its_database(monkeypatch, stage):
    events = []
    connection = FakeConnection(
        stage,
        events,
        [(91,)] if stage == METADATA else [(17,), (101,)],
    )
    install_connections(monkeypatch, events, (stage, connection))

    result = apply_module.apply_plan(single_stage_plan(stage))

    assert result.status == ApplyStatus.SUCCESS
    assert result.metadata_status == (
        ApplyStageStatus.COMMITTED
        if stage == METADATA
        else ApplyStageStatus.NOT_REQUIRED
    )
    assert result.raw_status == (
        ApplyStageStatus.COMMITTED
        if stage == RAW
        else ApplyStageStatus.NOT_REQUIRED
    )
    assert events[0] == (stage, "connect")
    assert events[-2:] == [(stage, "commit"), (stage, "close")]
    assert identities(result) == (
        [("deployment", 91)]
        if stage == METADATA
        else [("interface", 101), ("file", 17)]
    )


def test_combined_success_transfers_ids_after_metadata_commit(monkeypatch):
    events = []
    metadata = FakeConnection(METADATA, events, [(91,)])
    raw = FakeConnection(RAW, events, [(17,), (101,)])
    install_connections(
        monkeypatch,
        events,
        (METADATA, metadata),
        (RAW, raw),
    )
    contexts = []
    creation_events = []

    def fresh_context():
        context = ApplyContext()
        contexts.append(context)
        creation_events.append(tuple(events))
        return context

    monkeypatch.setattr(apply_module, "ApplyContext", fresh_context)

    result = apply_module.apply_plan(combined_plan())

    assert result.status == ApplyStatus.SUCCESS
    assert result.metadata_status == ApplyStageStatus.COMMITTED
    assert result.raw_status == ApplyStageStatus.COMMITTED
    assert identities(result) == [
        ("deployment", 91),
        ("interface", 101),
        ("file", 17),
    ]
    assert events.index((METADATA, "close")) < events.index((RAW, "connect"))
    assert raw.calls[1][1][:2] == (17, 91)
    assert len(contexts) == 2
    assert contexts[0] is not contexts[1]
    assert (METADATA, "commit") in creation_events[1]
    assert contexts[1].resolve(
        PlannedRef("deployment", "deployment")
    ) == 91

    with pytest.raises(ApplyError):
        contexts[0].resolve(PlannedRef("file", "file"))


@pytest.mark.parametrize("case", ["metadata", "raw", "confirmation"])
def test_preparation_failure_happens_before_connecting(case):
    plan = combined_plan()

    if case == "metadata":
        plan = replace(
            plan,
            metadata_items=(
                replace(deployment_item(), values=object()),
            ),
        )
    elif case == "raw":
        file = file_item()
        plan = replace(
            plan,
            raw_items=(
                replace(
                    file,
                    values=replace(file.values, reader_config=[]),
                ),
            ),
        )
    else:
        plan = replace(
            plan,
            raw_items=(
                replace(file_item(), confirmation_required=True),
            ),
        )

    with pytest.raises(ApplyError) as caught:
        apply_module.apply_plan(plan)

    assert caught.value.code == (
        ApplyErrorCode.CONFIRMATION_REQUIRED
        if case == "confirmation"
        else ApplyErrorCode.PLAN_NOT_APPLICABLE
    )


def test_confirmation_reaches_combined_preparation(monkeypatch):
    events = []
    raw = FakeConnection(RAW, events, [(17,)])
    install_connections(monkeypatch, events, (RAW, raw))
    plan = ResolvedPlan(
        raw_items=(
            replace(file_item(), confirmation_required=True),
        ),
    )

    result = apply_module.apply_plan(
        plan,
        confirm_identity_changes=True,
    )

    assert result.status == ApplyStatus.SUCCESS
    assert result.raw_status == ApplyStageStatus.COMMITTED


@pytest.mark.parametrize("stage", [METADATA, RAW])
@pytest.mark.parametrize(
    "phase",
    ["connect", "execution", "rollback", "commit", "close"],
)
def test_combined_failure_reports_known_stage_outcomes(
    monkeypatch,
    stage,
    phase,
):
    events = []
    metadata = FakeConnection(METADATA, events, [(91,)])
    raw = FakeConnection(RAW, events, [(17,), (101,)])
    failing = metadata if stage == METADATA else raw
    failing.failure_phase = phase
    failing.fail_at = 1 if stage == METADATA else 2

    metadata_entry = (
        failing.failure
        if stage == METADATA and phase == "connect"
        else metadata
    )
    raw_entry = (
        failing.failure
        if stage == RAW and phase == "connect"
        else raw
    )
    install_connections(
        monkeypatch,
        events,
        (METADATA, metadata_entry),
        (RAW, raw_entry),
    )

    with pytest.raises(ApplyExecutionError) as caught:
        apply_module.apply_plan(combined_plan())

    result = caught.value.result
    stage_error = caught.value.__cause__

    assert isinstance(stage_error, StageTransactionError)
    assert stage_error.__cause__ is failing.failure

    if phase == "rollback":
        assert stage_error.rollback_error is failing.rollback_error
    if phase == "close":
        assert stage_error.close_error is failing.failure

    stage_status = {
        "connect": ApplyStageStatus.FAILED,
        "execution": ApplyStageStatus.FAILED,
        "rollback": ApplyStageStatus.UNKNOWN,
        "commit": ApplyStageStatus.UNKNOWN,
        "close": ApplyStageStatus.COMMITTED,
    }[phase]

    if stage == METADATA:
        assert result.metadata_status == stage_status
        assert result.raw_status == ApplyStageStatus.NOT_STARTED
        assert (RAW, "connect") not in events
        assert identities(result) == (
            [("deployment", 91)] if phase == "close" else []
        )
        expected_status = (
            ApplyStatus.PARTIAL
            if phase == "close"
            else ApplyStatus.UNKNOWN
            if phase in {"commit", "rollback"}
            else ApplyStatus.FAILED
        )
    else:
        assert result.metadata_status == ApplyStageStatus.COMMITTED
        assert result.raw_status == stage_status
        assert identities(result) == (
            [("deployment", 91), ("interface", 101), ("file", 17)]
            if phase == "close"
            else [("deployment", 91)]
        )
        expected_status = (
            ApplyStatus.SUCCESS
            if phase == "close"
            else ApplyStatus.UNKNOWN
            if phase in {"commit", "rollback"}
            else ApplyStatus.PARTIAL
        )

    assert result.status == expected_status
    assert events.count((METADATA, "connect")) == 1
    assert events.count((RAW, "connect")) == (0 if stage == METADATA else 1)


@pytest.mark.parametrize("stage", [METADATA, RAW])
def test_cleanup_failure_includes_completed_reuse_stage(monkeypatch, stage):
    events = []
    reused = reuse_plan()

    if stage == METADATA:
        plan = replace(
            reused,
            metadata_items=(deployment_item(),),
        )
        rows = [(92,)]
        expected = [
            ("deployment", 92),
            ("interface", 101),
            ("file", 17),
        ]
    else:
        plan = replace(
            single_stage_plan(RAW),
            metadata_items=reused.metadata_items,
        )
        rows = [(27,), (201,)]
        expected = [
            ("deployment", 91),
            ("interface", 201),
            ("file", 27),
        ]

    connection = FakeConnection(
        stage,
        events,
        rows,
        failure_phase="close",
    )
    install_connections(monkeypatch, events, (stage, connection))

    with pytest.raises(ApplyExecutionError) as caught:
        apply_module.apply_plan(plan)

    assert caught.value.result.status == ApplyStatus.SUCCESS
    assert identities(caught.value.result) == expected


@pytest.mark.parametrize("stage", [METADATA, RAW])
@pytest.mark.parametrize("phase", ["commit", "close"])
def test_single_stage_error_has_valid_overall_outcome(
    monkeypatch,
    stage,
    phase,
):
    events = []
    connection = FakeConnection(
        stage,
        events,
        [(91,)] if stage == METADATA else [(17,), (101,)],
        failure_phase=phase,
    )
    install_connections(monkeypatch, events, (stage, connection))

    with pytest.raises(ApplyExecutionError) as caught:
        apply_module.apply_plan(single_stage_plan(stage))

    result = caught.value.result

    assert result.status == (
        ApplyStatus.UNKNOWN if phase == "commit" else ApplyStatus.SUCCESS
    )
    assert (
        result.raw_status if stage == METADATA else result.metadata_status
    ) == ApplyStageStatus.NOT_REQUIRED

    if phase == "commit":
        assert result.items == ()
    else:
        assert identities(result) == (
            [("deployment", 91)]
            if stage == METADATA
            else [("interface", 101), ("file", 17)]
        )


@pytest.mark.parametrize("case", ["missing", "wrong-resource"])
def test_invalid_committed_dependency_prevents_raw_sql(monkeypatch, case):
    events = []
    metadata = FakeConnection(METADATA, events, [])
    raw = FakeConnection(RAW, events, [])
    install_connections(
        monkeypatch,
        events,
        (METADATA, metadata),
        (RAW, raw),
    )
    supplied = (
        ()
        if case == "missing"
        else (
            ApplyItemResult(
                plan_id="deployment",
                resource_type="site",
                action=PlanAction.CREATE,
                database_id=91,
            ),
        )
    )

    monkeypatch.setattr(
        apply_module,
        "execute_metadata_preparation",
        lambda connection, prepared, context: supplied,
    )

    with pytest.raises(ApplyExecutionError) as caught:
        apply_module.apply_plan(combined_plan())

    assert caught.value.result.status == ApplyStatus.PARTIAL
    assert raw.calls == []
    stage_error = caught.value.__cause__
    assert isinstance(stage_error, StageTransactionError)
    assert isinstance(stage_error.__cause__, ApplyError)
    assert (
        stage_error.__cause__.code
        == ApplyErrorCode.UNRESOLVED_PLANNED_REF
    )


def test_new_attempt_uses_fresh_context_after_raw_rollback(monkeypatch):
    events = []
    first = FakeConnection(
        RAW,
        events,
        [(17,)],
        failure_phase="execution",
        fail_at=2,
    )
    second = FakeConnection(RAW, events, [(27,), (201,)])
    install_connections(
        monkeypatch,
        events,
        (RAW, first),
        (RAW, second),
    )
    contexts = []

    def fresh_context():
        context = ApplyContext()
        contexts.append(context)
        return context

    monkeypatch.setattr(apply_module, "ApplyContext", fresh_context)
    plan = single_stage_plan(RAW)

    with pytest.raises(ApplyExecutionError):
        apply_module.apply_plan(plan)

    assert events.count((RAW, "connect")) == 1

    result = apply_module.apply_plan(plan)

    assert events.count((RAW, "connect")) == 2
    assert len(contexts) == 4
    assert len({id(context) for context in contexts}) == 4
    assert contexts[1].resolve(PlannedRef("file", "file")) == 17
    assert contexts[3].resolve(PlannedRef("file", "file")) == 27
    assert second.calls[1][1][:2] == (27, 91)
    assert identities(result) == [("interface", 201), ("file", 27)]


def test_raw_failure_after_metadata_reuse_is_failed_not_partial(monkeypatch):
    events = []
    raw = FakeConnection(
        RAW,
        events,
        [(17,)],
        failure_phase="execution",
        fail_at=2,
    )
    install_connections(monkeypatch, events, (RAW, raw))
    plan = replace(
        single_stage_plan(RAW),
        metadata_items=reuse_plan().metadata_items,
    )

    with pytest.raises(ApplyExecutionError) as caught:
        apply_module.apply_plan(plan)

    result = caught.value.result
    assert result.status == ApplyStatus.FAILED
    assert result.metadata_status == ApplyStageStatus.NOT_REQUIRED
    assert result.raw_status == ApplyStageStatus.FAILED
    assert identities(result) == [("deployment", 91)]


def test_public_api_exports_apply_plan():
    assert persistence.apply_plan is apply_module.apply_plan

