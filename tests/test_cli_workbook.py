import argparse

from dendroflow import config
from dendroflow.cli import workbook


def test_offline_workbook_environment_only_requires_the_label(monkeypatch):
    monkeypatch.setattr(config, "load_env", lambda _path: {})
    monkeypatch.setenv("DENDROFLOW_ENVIRONMENT", "local-dev")
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    assert workbook.require_workbook_environment() == "local-dev"


def test_missing_workbook_environment_is_reported_as_configuration_error(
    monkeypatch, capsys,
):
    monkeypatch.setattr(config, "load_env", lambda _path: {})
    monkeypatch.delenv("DENDROFLOW_ENVIRONMENT", raising=False)

    assert workbook.require_workbook_environment() is None
    captured = capsys.readouterr()
    assert "DENDROFLOW_ENVIRONMENT" in captured.err


def test_database_workbook_runner_passes_captured_target_and_context(
    monkeypatch,
):
    target = config.DatabaseTarget("local-dev", {"host": "db.example"})
    monkeypatch.setattr(workbook, "get_database_target", lambda: target)
    observed = {}

    def operation(args, passed_target):
        observed["args"] = args
        observed["target"] = passed_target
        return 0

    args = argparse.Namespace(output="export.xlsx")
    assert workbook.run_with_database_target(args, operation) == 0
    assert observed == {"args": args, "target": target}
