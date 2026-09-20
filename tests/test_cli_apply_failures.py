from collections import Counter
from dataclasses import replace

import psycopg
import pytest

from dendroflow import database
from dendroflow.cli import configuration
from dendroflow.cli.main import main
from dendroflow.cli.reporting import format_apply_error
from dendroflow.configuration.persistence import (
    ApplyError,
    ApplyErrorCode,
    ApplyExecutionError,
    ApplyResult,
    ApplyStageStatus,
    ApplyStatus,
)
from dendroflow.configuration.plan import (
    FieldChange,
    PlanAction,
    ResolvedFileValues,
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSiteValues,
)


@pytest.fixture(autouse=True)
def block_real_io(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Unexpected real database connection or prompt")

    monkeypatch.setattr(psycopg, "connect", unexpected)
    monkeypatch.setattr("builtins.input", unexpected)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)


def make_plan(scope="both"):
    metadata_item = ResolvedPlanItem(
        "site:update", "site", PlanAction.UPDATE,
        ResolvedSiteValues("station", "Station"),
        database_id=7,
        changes=(FieldChange("name", "Old", "Station"),),
    )
    raw_item = ResolvedPlanItem(
        "file:new", "file", PlanAction.CREATE,
        ResolvedFileValues(
            "/data/logger.csv", "UTC", "%Y",
            {"reader": "csv", "options": {}},
        ),
    )
    return ResolvedPlan(
        metadata_items=() if scope == "raw" else (metadata_item,),
        raw_items=() if scope == "metadata" else (raw_item,),
    )


def arrange_plan(monkeypatch, tmp_path, plan):
    path = tmp_path / "config.yaml"
    path.write_text("{}", encoding="utf-8")
    resolutions = []

    def resolve(config):
        resolutions.append(config)
        return plan

    monkeypatch.setattr(configuration, "resolve_config", resolve)
    return path, resolutions


class FakeConnection:
    def __init__(self, stage, failures, events):
        self.stage = stage
        self.failures = failures
        self.events = events

    def execute(self, statement, parameters):
        self.events.append((self.stage, "execute"))
        if "execute" in self.failures:
            raise psycopg.OperationalError(f"{self.stage} execute failed")
        return self

    def fetchone(self):
        if "stale" in self.failures:
            return None
        return (7 if self.stage == "metadata" else 8,)

    def commit(self):
        self.events.append((self.stage, "commit"))
        if "commit" in self.failures:
            raise psycopg.OperationalError(f"{self.stage} commit failed")

    def rollback(self):
        self.events.append((self.stage, "rollback"))
        if "rollback" in self.failures:
            raise psycopg.OperationalError(f"{self.stage} rollback failed")

    def close(self):
        self.events.append((self.stage, "close"))
        if "close" in self.failures:
            raise OSError(f"{self.stage} close failed")


@pytest.mark.parametrize(
    ("scope", "stage", "failures", "status", "metadata", "raw", "exit_code"),
    [
        ("both", "metadata", ("connect",),
         "FAILED", "FAILED", "NOT_STARTED", 1),
        ("both", "metadata", ("stale",),
         "FAILED", "FAILED", "NOT_STARTED", 1),
        ("both", "metadata", ("commit",),
         "UNKNOWN", "UNKNOWN", "NOT_STARTED", 5),
        ("both", "metadata", ("stale", "rollback", "close"),
         "UNKNOWN", "UNKNOWN", "NOT_STARTED", 5),
        ("both", "metadata", ("close",),
         "PARTIAL", "COMMITTED", "NOT_STARTED", 4),
        ("both", "raw", ("connect",),
         "PARTIAL", "COMMITTED", "FAILED", 4),
        ("both", "raw", ("execute",),
         "PARTIAL", "COMMITTED", "FAILED", 4),
        ("both", "raw", ("commit",),
         "UNKNOWN", "COMMITTED", "UNKNOWN", 5),
        ("both", "raw", ("execute", "rollback"),
         "UNKNOWN", "COMMITTED", "UNKNOWN", 5),
        ("both", "raw", ("close",),
         "SUCCESS", "COMMITTED", "COMMITTED", 1),
        ("metadata", "metadata", ("close",),
         "SUCCESS", "COMMITTED", "NOT_REQUIRED", 1),
        ("metadata", "metadata", ("stale",),
         "FAILED", "FAILED", "NOT_REQUIRED", 1),
        ("metadata", "metadata", ("commit",),
         "UNKNOWN", "UNKNOWN", "NOT_REQUIRED", 5),
        ("raw", "raw", ("connect",),
         "FAILED", "NOT_REQUIRED", "FAILED", 1),
        ("raw", "raw", ("commit",),
         "UNKNOWN", "NOT_REQUIRED", "UNKNOWN", 5),
        ("raw", "raw", ("close",),
         "SUCCESS", "NOT_REQUIRED", "COMMITTED", 1),
    ],
)
def test_real_apply_failure_reporting(
    scope, stage, failures, status, metadata, raw, exit_code,
    monkeypatch, tmp_path, capsys,
):
    path, resolutions = arrange_plan(monkeypatch, tmp_path, make_plan(scope))
    events = []

    def connect(name):
        current_stage = name.removeprefix("dendroflow_")
        events.append((current_stage, "connect"))
        current_failures = failures if current_stage == stage else ()
        if "connect" in current_failures:
            raise psycopg.OperationalError(f"{current_stage} connect failed")
        return FakeConnection(current_stage, current_failures, events)

    monkeypatch.setattr(database, "connect", connect)

    assert main(["config", "apply", str(path), "--yes"]) == exit_code
    assert len(resolutions) == 1
    assert all(count == 1 for count in Counter(events).values())

    captured = capsys.readouterr()
    outcome = captured.out.split("Database outcome:", 1)[1]
    assert outcome.startswith(f" {status}\n")
    assert f"METADATA: {metadata}" in outcome
    assert f"RAW: {raw}" in outcome
    assert ("UPDATE site 'site:update' (database_id=7)" in outcome) == (
        metadata == "COMMITTED"
    )
    assert ("CREATE file 'file:new' (database_id=8)" in outcome) == (
        raw == "COMMITTED"
    )
    if raw == "NOT_STARTED":
        assert ("raw", "connect") not in events

    assert "Apply did not finish cleanly:" in captured.err
    assert "No automatic retry was attempted." in captured.err
    assert "Traceback" not in captured.err

    for failure in failures:
        if failure == "stale":
            assert "ApplyError [STALE_PLAN]" in captured.err
            assert "The plan is stale." in captured.err
        else:
            assert f"{stage} {failure} failed" in captured.err

    if "rollback" in failures:
        assert "Rollback error:" in captured.err
    if "close" in failures:
        assert "Close error:" in captured.err
        assert captured.err.count(f"{stage} close failed") == 1

    if status == "SUCCESS":
        assert "Required database work completed; cleanup failed." in captured.err
        assert "Do not repeat committed operations" in captured.err
    elif status == "FAILED":
        assert "No write stage is reported as committed." in captured.err
    elif status == "PARTIAL":
        assert "METADATA committed; required RAW work did not complete." in outcome
    elif status == "UNKNOWN":
        assert "Missing item results do not prove rollback." in outcome


@pytest.mark.parametrize(
    ("code", "expected_exit"),
    [
        (ApplyErrorCode.PLAN_NOT_APPLICABLE, 2),
        (ApplyErrorCode.CONFIRMATION_REQUIRED, 3),
    ],
)
def test_apply_boundary_rejection_has_no_execution_outcome(
    code, expected_exit, monkeypatch, tmp_path, capsys,
):
    path, resolutions = arrange_plan(monkeypatch, tmp_path, make_plan())
    calls = []

    def reject(plan, **kwargs):
        calls.append(plan)
        raise ApplyError(code, "Rejected before execution")

    monkeypatch.setattr(configuration, "apply_plan", reject)

    assert main(["config", "apply", str(path), "--yes"]) == expected_exit
    assert len(calls) == len(resolutions) == 1
    captured = capsys.readouterr()
    assert "Database outcome:" not in captured.out
    assert f"Apply blocked [{code.value.upper()}]" in captured.err


def failed_outcome():
    return ApplyResult(
        ApplyStatus.FAILED,
        ApplyStageStatus.FAILED,
        ApplyStageStatus.NOT_STARTED,
    )


def test_error_without_cause_does_not_invent_one(capsys):
    error = ApplyExecutionError("Execution failed", result=failed_outcome())

    report = format_apply_error(error)

    assert "Execution failed" in report
    assert "Cause:" not in report
    assert "Rollback error:" not in report
    assert "Close error:" not in report
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_explicit_cause_chain_is_preserved():
    original = ValueError("Invalid stored value")
    intermediate = RuntimeError("Could not execute operation")
    intermediate.__cause__ = original
    error = ApplyExecutionError("Execution failed", result=failed_outcome())
    error.__cause__ = intermediate

    report = format_apply_error(error)

    assert "Cause: RuntimeError: Could not execute operation" in report
    assert "Cause: ValueError: Invalid stored value" in report
    assert error.__cause__ is intermediate
    assert intermediate.__cause__ is original


def test_cyclic_cause_chain_is_bounded():
    cause = RuntimeError("Repeated cause")
    cause.__cause__ = cause
    error = ApplyExecutionError("Execution failed", result=failed_outcome())
    error.__cause__ = cause

    assert format_apply_error(error).count("Repeated cause") == 1


def test_completed_reuse_results_survive_metadata_failure(
    monkeypatch, tmp_path, capsys,
):
    plan = make_plan()
    reused_file = replace(
        plan.raw_items[0], action=PlanAction.REUSE, database_id=8,
    )
    plan = replace(plan, raw_items=(reused_file,))
    path, _ = arrange_plan(monkeypatch, tmp_path, plan)
    connections = []

    def fail_connection(name):
        connections.append(name)
        raise psycopg.OperationalError("metadata unavailable")

    monkeypatch.setattr(database, "connect", fail_connection)

    assert main(["config", "apply", str(path), "--yes"]) == 1
    assert connections == ["dendroflow_metadata"]
    outcome = capsys.readouterr().out.split("Database outcome:", 1)[1]
    assert "FAILED" in outcome
    assert "RAW: NOT_REQUIRED" in outcome
    assert "REUSE file 'file:new' (database_id=8)" in outcome
    assert "UPDATE site 'site:update'" not in outcome

