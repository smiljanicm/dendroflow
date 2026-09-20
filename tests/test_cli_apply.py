import runpy
import sys
from dataclasses import replace

import psycopg
import pytest

from dendroflow.cli import configuration
from dendroflow.cli.main import main
from dendroflow.configuration.persistence import (
    ApplyExecutionError,
    ApplyItemResult,
    ApplyResult,
    ApplyStageStatus,
    ApplyStatus,
)
from dendroflow.configuration.persistence import apply_plan as real_apply_plan
from dendroflow.configuration.plan import (
    FieldChange,
    PlanAction,
    PlanError,
    PlanErrorCode,
    ResolvedFileValues,
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSiteValues,
)


@pytest.fixture(autouse=True)
def block_unexpected_io(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Unexpected database, apply, or input call")

    monkeypatch.setattr(psycopg, "connect", unexpected)
    monkeypatch.setattr(configuration, "apply_plan", unexpected)
    monkeypatch.setattr("builtins.input", unexpected)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)


def write_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("{}", encoding="utf-8")
    return path


def site_item():
    return ResolvedPlanItem(
        "site:new", "site", PlanAction.CREATE,
        ResolvedSiteValues("station", "Station"),
    )


def use_plan(monkeypatch, plan):
    calls = []

    def resolve(config):
        calls.append(config)
        return plan

    monkeypatch.setattr(configuration, "resolve_config", resolve)
    return calls


def success_result(plan):
    return ApplyResult(
        ApplyStatus.SUCCESS,
        (
            ApplyStageStatus.COMMITTED
            if plan.metadata_items else ApplyStageStatus.NOT_REQUIRED
        ),
        (
            ApplyStageStatus.COMMITTED
            if plan.raw_items else ApplyStageStatus.NOT_REQUIRED
        ),
        tuple(
            ApplyItemResult(item.plan_id, item.resource_type, item.action, index)
            for index, item in enumerate(plan.items, start=7)
        ),
    )


@pytest.mark.parametrize("stage", ["metadata", "raw", "combined"])
def test_apply_executes_exact_reviewed_plan_once(
    stage, monkeypatch, tmp_path, capsys,
):
    file = ResolvedPlanItem(
        "file:new", "file", PlanAction.CREATE,
        ResolvedFileValues(
            "/data/logger.csv", "UTC", "%Y",
            {"reader": "csv", "options": {}},
        ),
    )
    plan = ResolvedPlan(
        metadata_items=() if stage == "raw" else (site_item(),),
        raw_items=() if stage == "metadata" else (file,),
    )
    resolutions = use_plan(monkeypatch, plan)
    reviewed = []
    executed = []
    original_review = configuration.review_for_apply

    def review(actual, **kwargs):
        reviewed.append(actual)
        return original_review(actual, **kwargs)

    def execute(actual, *, confirm_identity_changes):
        assert actual is plan
        assert reviewed == [plan]
        assert reviewed[0] is actual
        assert confirm_identity_changes is False
        assert "Configuration plan" in capsys.readouterr().out
        executed.append(actual)
        return success_result(actual)

    monkeypatch.setattr(configuration, "review_for_apply", review)
    monkeypatch.setattr(configuration, "apply_plan", execute)
    path = write_config(tmp_path)

    assert main(["config", "apply", str(path), "--yes"]) == 0
    assert len(resolutions) == len(executed) == 1
    captured = capsys.readouterr()
    assert "Database outcome: SUCCESS" in captured.out
    assert "database_id=7" in captured.out
    assert captured.err == ""


def test_interactive_identity_update_uses_original_plan(
    monkeypatch, tmp_path, capsys,
):
    item = replace(
        site_item(),
        action=PlanAction.UPDATE,
        database_id=7,
        changes=(FieldChange("site_code", "old", "station", True),),
    )
    plan = ResolvedPlan(metadata_items=(item,))
    resolutions = use_plan(monkeypatch, plan)
    path = write_config(tmp_path)
    events = []
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def accept(prompt):
        assert prompt == "Apply this plan? [y/N] "
        assert "[identity change]" in capsys.readouterr().out
        events.append("confirm")
        # The command must not reload or re-resolve after review.
        path.write_text("invalid: [", encoding="utf-8")
        return "yes"

    def execute(actual, *, confirm_identity_changes):
        assert actual is plan
        assert confirm_identity_changes is True
        assert events == ["confirm"]
        events.append("execute")
        return success_result(actual)

    monkeypatch.setattr("builtins.input", accept)
    monkeypatch.setattr(configuration, "apply_plan", execute)

    assert main([
        "config", "apply", str(path), "--confirm-identity-changes",
    ]) == 0
    assert len(resolutions) == 1
    assert events == ["confirm", "execute"]
    assert "Database outcome: SUCCESS" in capsys.readouterr().out


@pytest.mark.parametrize("reuse", [False, True])
def test_no_write_plans_use_real_apply_without_connections(
    reuse, monkeypatch, tmp_path, capsys,
):
    items = (
        (replace(site_item(), action=PlanAction.REUSE, database_id=7),)
        if reuse else ()
    )
    plan = ResolvedPlan(metadata_items=items)
    use_plan(monkeypatch, plan)
    monkeypatch.setattr(configuration, "apply_plan", real_apply_plan)
    path = write_config(tmp_path)

    assert main(["config", "apply", str(path)]) == 0
    captured = capsys.readouterr()
    assert "Database outcome: SUCCESS" in captured.out
    assert "METADATA: NOT_REQUIRED" in captured.out
    assert "RAW: NOT_REQUIRED" in captured.out
    if reuse:
        assert "REUSE site 'site:new' (database_id=7)" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("reason", ["noninteractive", "declined", "identity"])
def test_missing_or_declined_confirmation_prevents_apply(
    reason, monkeypatch, tmp_path, capsys,
):
    item = site_item()
    options = []
    if reason == "declined":
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda prompt: "no")
    elif reason == "identity":
        item = replace(
            item,
            action=PlanAction.UPDATE,
            database_id=7,
            changes=(FieldChange("site_code", "old", "station", True),),
        )
        options = ["--yes"]
    use_plan(monkeypatch, ResolvedPlan(metadata_items=(item,)))
    path = write_config(tmp_path)

    assert main(["config", "apply", str(path), *options]) == 3
    captured = capsys.readouterr()
    assert captured.err
    assert "Database outcome:" not in captured.out


def test_plan_errors_prevent_apply_even_with_both_flags(
    monkeypatch, tmp_path, capsys,
):
    plan = ResolvedPlan(
        metadata_items=(site_item(),),
        errors=(PlanError(PlanErrorCode.CONFLICT, "site", "sites[0]", "Conflict"),),
    )
    use_plan(monkeypatch, plan)
    path = write_config(tmp_path)

    assert main([
        "config", "apply", str(path), "--yes", "--confirm-identity-changes",
    ]) == 2
    assert "Apply blocked" in capsys.readouterr().err


def test_preparation_failure_prevents_apply(monkeypatch, tmp_path, capsys):
    item = replace(site_item(), resource_type="unsupported")
    use_plan(monkeypatch, ResolvedPlan(metadata_items=(item,)))
    path = write_config(tmp_path)

    assert main(["config", "apply", str(path), "--yes"]) == 2
    assert "Preparation failed" in capsys.readouterr().err


def test_invalid_input_stops_before_resolution(monkeypatch, tmp_path, capsys):
    def unexpected_resolution(config):
        pytest.fail("Invalid input must not reach resolution")

    monkeypatch.setattr(configuration, "resolve_config", unexpected_resolution)
    path = write_config(tmp_path)
    path.write_text("sites: [", encoding="utf-8")

    assert main(["config", "apply", str(path), "--yes"]) == 2
    assert "Configuration validation failed" in capsys.readouterr().err


def test_lookup_failure_prevents_apply(monkeypatch, tmp_path, capsys):
    def fail_resolution(config):
        raise psycopg.OperationalError("database unavailable")

    monkeypatch.setattr(configuration, "resolve_config", fail_resolution)
    path = write_config(tmp_path)

    assert main(["config", "apply", str(path), "--yes"]) == 1
    assert "Configuration planning failed" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("raw_status", "overall_status", "expected_code"),
    [
        (ApplyStageStatus.FAILED, ApplyStatus.PARTIAL, 4),
        (ApplyStageStatus.UNKNOWN, ApplyStatus.UNKNOWN, 5),
        (ApplyStageStatus.COMMITTED, ApplyStatus.SUCCESS, 1),
    ],
)
def test_execution_error_reports_known_outcome(
    raw_status, overall_status, expected_code,
    monkeypatch, tmp_path, capsys,
):
    file = ResolvedPlanItem(
        "file:new", "file", PlanAction.CREATE,
        ResolvedFileValues("/data/logger.csv", "UTC", "%Y", {}),
    )
    plan = ResolvedPlan(metadata_items=(site_item(),), raw_items=(file,))
    use_plan(monkeypatch, plan)
    path = write_config(tmp_path)
    completed = (
        ApplyItemResult("site:new", "site", PlanAction.CREATE, 7),
    )
    if raw_status == ApplyStageStatus.COMMITTED:
        completed += (ApplyItemResult("file:new", "file", PlanAction.CREATE, 8),)
    outcome = ApplyResult(
        overall_status, ApplyStageStatus.COMMITTED, raw_status, completed,
    )
    calls = []

    def fail_apply(actual, **kwargs):
        calls.append(actual)
        raise ApplyExecutionError("Stage did not finish cleanly", result=outcome)

    monkeypatch.setattr(configuration, "apply_plan", fail_apply)

    assert main(["config", "apply", str(path), "--yes"]) == expected_code
    assert len(calls) == 1
    captured = capsys.readouterr()
    assert f"Database outcome: {overall_status.value.upper()}" in captured.out
    assert "METADATA: COMMITTED" in captured.out
    assert "Apply did not finish cleanly" in captured.err


@pytest.mark.parametrize(
    ("argv", "expected_code"),
    [
        (["config", "apply", "--help"], 0),
        (["config", "apply"], 2),
        (["config", "apply", "config.yaml", "--unknown"], 2),
    ],
)
def test_apply_argument_handling(argv, expected_code):
    with pytest.raises(SystemExit) as caught:
        main(argv)
    assert caught.value.code == expected_code


def test_module_entry_point_runs_empty_apply(tmp_path, monkeypatch, capsys):
    path = write_config(tmp_path)
    monkeypatch.setattr(configuration, "apply_plan", real_apply_plan)
    monkeypatch.setattr(sys, "argv", ["dendroflow", "config", "apply", str(path)])

    with pytest.raises(SystemExit) as caught:
        runpy.run_module("dendroflow", run_name="__main__")

    assert caught.value.code == 0
    assert "Database outcome: SUCCESS" in capsys.readouterr().out

