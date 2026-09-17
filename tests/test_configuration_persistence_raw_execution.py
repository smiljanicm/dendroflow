from dataclasses import replace
from datetime import datetime, timezone

import pytest

from dendroflow.configuration.persistence.context import ApplyContext
from dendroflow.configuration.persistence.models import (
    ApplyError,
    ApplyErrorCode,
    ApplyItemResult,
)
from dendroflow.configuration.persistence.raw_execution import (
    execute_raw_preparation,
)
from dendroflow.configuration.persistence.raw_preparation import (
    prepare_raw_plan,
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


class FakeConnection:
    def __init__(
        self,
        rows=(),
        *,
        failure=None,
        failure_stage=None,
        failure_at=2,
    ):
        self.rows = iter(rows)
        self.failure = failure
        self.failure_stage = failure_stage
        self.failure_at = failure_at
        self.calls = []
        self.fetchone_calls = 0

    def execute(self, query, params):
        self.calls.append((query, params))

        if (
            self.failure_stage == "execute"
            and len(self.calls) == self.failure_at
        ):
            raise self.failure

        return self

    def fetchone(self):
        self.fetchone_calls += 1

        if (
            self.failure_stage == "fetchone"
            and len(self.calls) == self.failure_at
        ):
            raise self.failure

        return next(self.rows)


def file_item(plan_id="file"):
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="file",
        action=PlanAction.CREATE,
        values=ResolvedFileValues(
            filepath=f"/data/{plan_id}.csv",
            timestamp_timezone="UTC",
            timestamp_format="%Y-%m-%d %H:%M:%S",
            reader_config={"reader": "csv", "options": {}},
        ),
    )


def interface_item(plan_id="interface", *, deployment=None):
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="interface",
        action=PlanAction.CREATE,
        values=ResolvedInterfaceValues(
            file=PlannedRef("file", "file"),
            deployment=(
                ExistingRef("deployment", 91)
                if deployment is None
                else deployment
            ),
            values_column=plan_id,
            timestamp_column="TIMESTAMP",
            unit="cm",
        ),
    )


def deployment_item(plan_id):
    return ResolvedPlanItem(
        plan_id=plan_id,
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


def combined_preparation():
    return prepare_raw_plan(
        ResolvedPlan(
            metadata_items=(
                deployment_item("deployment-a"),
                deployment_item("deployment-b"),
            ),
            raw_items=(
                file_item(),
                interface_item(
                    "first",
                    deployment=PlannedRef(
                        "deployment",
                        "deployment-a",
                    ),
                ),
                interface_item(
                    "second",
                    deployment=PlannedRef(
                        "deployment",
                        "deployment-b",
                    ),
                ),
            ),
        ),
        allow_metadata_dependencies=True,
    )


def assert_unregistered(context, resource_type, plan_id):
    with pytest.raises(ApplyError) as caught:
        context.resolve(PlannedRef(resource_type, plan_id))

    assert caught.value.code == ApplyErrorCode.UNRESOLVED_PLANNED_REF


def test_empty_preparation_returns_no_results():
    prepared = prepare_raw_plan(ResolvedPlan())
    connection = FakeConnection()

    results = execute_raw_preparation(
        connection,
        prepared,
        ApplyContext(),
    )

    assert results == ()
    assert connection.calls == []
    assert connection.fetchone_calls == 0


def test_reuse_only_returns_existing_ids_without_sql_or_registration():
    file = replace(
        file_item(),
        action=PlanAction.REUSE,
        database_id=17,
    )
    interface = interface_item()
    interface = replace(
        interface,
        action=PlanAction.REUSE,
        database_id=101,
        values=replace(
            interface.values,
            file=ExistingRef("file", 17),
        ),
    )
    prepared = prepare_raw_plan(
        ResolvedPlan(raw_items=(interface, file))
    )
    connection = FakeConnection()
    context = ApplyContext()

    results = execute_raw_preparation(
        connection,
        prepared,
        context,
    )

    assert results == (
        ApplyItemResult(
            plan_id="interface",
            resource_type="interface",
            action=PlanAction.REUSE,
            database_id=101,
        ),
        ApplyItemResult(
            plan_id="file",
            resource_type="file",
            action=PlanAction.REUSE,
            database_id=17,
        ),
    )
    assert connection.calls == []
    assert connection.fetchone_calls == 0
    assert_unregistered(context, "file", "file")
    assert_unregistered(context, "interface", "interface")


def test_mixed_execution_preserves_original_result_order():
    reused = replace(
        file_item("reused"),
        action=PlanAction.REUSE,
        database_id=7,
    )
    original = (
        interface_item("first"),
        reused,
        file_item(),
        interface_item("second"),
    )
    prepared = prepare_raw_plan(
        ResolvedPlan(raw_items=original)
    )
    connection = FakeConnection(rows=[(17,), (101,), (102,)])
    context = ApplyContext()

    results = execute_raw_preparation(
        connection,
        prepared,
        context,
    )

    assert [
        (result.plan_id, result.action, result.database_id)
        for result in results
    ] == [
        ("first", PlanAction.CREATE, 101),
        ("reused", PlanAction.REUSE, 7),
        ("file", PlanAction.CREATE, 17),
        ("second", PlanAction.CREATE, 102),
    ]
    assert len(connection.calls) == 3
    assert "INSERT INTO files" in connection.calls[0][0]
    assert connection.calls[1][1] == (
        17, 91, "first", "TIMESTAMP", "cm",
    )
    assert connection.calls[2][1] == (
        17, 91, "second", "TIMESTAMP", "cm",
    )
    assert context.resolve(PlannedRef("file", "file")) == 17
    assert context.resolve(PlannedRef("interface", "first")) == 101
    assert context.resolve(PlannedRef("interface", "second")) == 102
    assert_unregistered(context, "file", "reused")


def test_execution_uses_supplied_metadata_registrations():
    prepared = combined_preparation()
    context = ApplyContext()

    for plan_id, database_id in (
        ("deployment-a", 91),
        ("deployment-b", 92),
    ):
        context.register(
            plan_id=plan_id,
            resource_type="deployment",
            database_id=database_id,
        )

    connection = FakeConnection(rows=[(17,), (101,), (102,)])

    results = execute_raw_preparation(
        connection,
        prepared,
        context,
    )

    assert [result.database_id for result in results] == [
        17, 101, 102,
    ]
    assert connection.calls[1][1][:2] == (17, 91)
    assert connection.calls[2][1][:2] == (17, 92)
    assert context.resolve(
        PlannedRef("deployment", "deployment-a")
    ) == 91
    assert context.resolve(
        PlannedRef("deployment", "deployment-b")
    ) == 92


@pytest.mark.parametrize(
    "missing",
    ["deployment-a", "deployment-b"],
)
def test_all_metadata_dependencies_are_checked_before_first_write(missing):
    prepared = combined_preparation()
    context = ApplyContext()

    for plan_id in ("deployment-a", "deployment-b"):
        if plan_id != missing:
            context.register(
                plan_id=plan_id,
                resource_type="deployment",
                database_id=91,
            )

    connection = FakeConnection(rows=[(17,), (101,), (102,)])

    with pytest.raises(ApplyError) as caught:
        execute_raw_preparation(connection, prepared, context)

    assert caught.value.code == ApplyErrorCode.UNRESOLVED_PLANNED_REF
    assert connection.calls == []
    assert connection.fetchone_calls == 0
    assert_unregistered(context, "file", "file")


def test_wrong_metadata_registration_type_fails_before_sql():
    prepared = combined_preparation()
    context = ApplyContext()
    context.register(
        plan_id="deployment-a",
        resource_type="deployment",
        database_id=91,
    )
    context.register(
        plan_id="deployment-b",
        resource_type="site",
        database_id=92,
    )
    connection = FakeConnection()

    with pytest.raises(ApplyError) as caught:
        execute_raw_preparation(connection, prepared, context)

    assert caught.value.code == ApplyErrorCode.UNRESOLVED_PLANNED_REF
    assert connection.calls == []
    assert_unregistered(context, "file", "file")


@pytest.mark.parametrize("failure_stage", ["execute", "fetchone"])
def test_writer_failure_stops_remaining_operations(failure_stage):
    prepared = prepare_raw_plan(
        ResolvedPlan(
            raw_items=(
                file_item(),
                interface_item("first"),
                interface_item("second"),
            )
        )
    )
    failure = RuntimeError("interface write failed")
    connection = FakeConnection(
        rows=[(17,)],
        failure=failure,
        failure_stage=failure_stage,
    )
    context = ApplyContext()

    with pytest.raises(RuntimeError) as caught:
        execute_raw_preparation(connection, prepared, context)

    assert caught.value is failure
    assert len(connection.calls) == 2
    assert connection.fetchone_calls == (
        1 if failure_stage == "execute" else 2
    )
    assert context.resolve(PlannedRef("file", "file")) == 17
    assert_unregistered(context, "interface", "first")
    assert_unregistered(context, "interface", "second")


def test_invalid_returned_id_stops_execution():
    prepared = prepare_raw_plan(
        ResolvedPlan(
            raw_items=(
                file_item(),
                interface_item("first"),
                interface_item("second"),
            )
        )
    )
    connection = FakeConnection(rows=[(17,), None])
    context = ApplyContext()

    with pytest.raises(
        ValueError,
        match="expected one returned database id",
    ):
        execute_raw_preparation(connection, prepared, context)

    assert len(connection.calls) == 2
    assert context.resolve(PlannedRef("file", "file")) == 17
    assert_unregistered(context, "interface", "first")
    assert_unregistered(context, "interface", "second")
