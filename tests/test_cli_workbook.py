import argparse
from types import SimpleNamespace

import pytest

from dendroflow import config
from dendroflow.cli import workbook
from dendroflow.cli.main import main


def test_offline_workbook_environment_only_requires_the_label(monkeypatch):
    monkeypatch.setattr(config, "load_env", lambda _path: {})
    monkeypatch.setenv("DENDROFLOW_ENVIRONMENT", "local-dev")
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    assert workbook.require_workbook_environment() == "local-dev"


def test_missing_workbook_environment_defaults_to_local(monkeypatch, capsys):
    monkeypatch.setattr(config, "load_env", lambda _path: {})
    monkeypatch.delenv("DENDROFLOW_ENVIRONMENT", raising=False)

    assert workbook.require_workbook_environment() == "local"
    assert capsys.readouterr().err == ""


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


def install_export_mocks(monkeypatch, *, scope="all", site_ids=()):
    target = config.DatabaseTarget(
        "local-dev",
        {"host": "localhost", "port": "5432", "user": "tester", "password": "secret"},
    )
    prepared = SimpleNamespace(
        scope=scope,
        site_ids=site_ids,
        frames={name: [] for name in (
            "sites", "location_types", "sensor_types", "variables", "sensor_models",
            "sensors", "locations", "location_labels", "deployments", "files", "interfaces",
        )},
    )
    calls = {}
    monkeypatch.setattr(workbook, "get_database_target", lambda: target)
    monkeypatch.setattr(workbook, "read_configuration_frames", lambda: calls.setdefault("read", True))

    def prepare(frames, *, site_ids):
        calls["frames"] = frames
        calls["site_ids"] = site_ids
        return prepared

    def write(path, export, *, target_environment):
        calls["write"] = (path, export, target_environment)

    monkeypatch.setattr(workbook, "prepare_workbook_export", prepare)
    monkeypatch.setattr(workbook, "write_workbook_export", write)
    return calls, prepared


def test_export_all_uses_environment_and_existing_workbook_apis(
    monkeypatch, tmp_path, capsys,
):
    calls, prepared = install_export_mocks(monkeypatch)
    output = tmp_path / "all.xlsx"

    assert main(["config", "workbook", "export", str(output), "--all"]) == 0

    assert calls["site_ids"] is None
    assert calls["write"] == (output, prepared, "local-dev")
    report = capsys.readouterr().out
    assert "Scope: all" in report
    assert "sites=0" in report


def test_export_accepts_repeated_site_ids(monkeypatch, tmp_path, capsys):
    calls, _ = install_export_mocks(monkeypatch, scope="sites", site_ids=(2, 3))
    output = tmp_path / "sites.xlsx"

    assert main([
        "config", "workbook", "export", str(output),
        "--site-id", "3", "--site-id", "2", "--site-id", "3",
    ]) == 0

    assert calls["site_ids"] == [3, 2, 3]
    assert "Selected site IDs: 2, 3" in capsys.readouterr().out


@pytest.mark.parametrize(
    "scope_args",
    [[], ["--all", "--site-id", "2"]],
)
def test_export_requires_exactly_one_scope_form(scope_args):
    with pytest.raises(SystemExit) as caught:
        main(["config", "workbook", "export", "control.xlsx", *scope_args])

    assert caught.value.code == 2


def test_existing_output_is_rejected_before_target_or_database_access(
    monkeypatch, tmp_path, capsys,
):
    output = tmp_path / "already.xlsx"
    output.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(
        workbook,
        "get_database_target",
        lambda: pytest.fail("target should not be resolved"),
    )

    assert main(["config", "workbook", "export", str(output), "--all"]) == 2

    assert output.read_text(encoding="utf-8") == "keep"
    assert "already exists" in capsys.readouterr().err


def test_export_rejects_bad_extension_before_database_access(monkeypatch, tmp_path):
    monkeypatch.setattr(
        workbook,
        "get_database_target",
        lambda: pytest.fail("target should not be resolved"),
    )

    assert main([
        "config", "workbook", "export", str(tmp_path / "control.csv"), "--all",
    ]) == 2


def install_validation_mocks(monkeypatch, *, scope="all", target_environment="local"):
    metadata = SimpleNamespace(
        target_environment=target_environment,
        scope=scope,
        site_ids=(2, 3) if scope == "sites" else (),
    )
    parsed = SimpleNamespace(
        metadata=metadata,
        frames={name: [] for name in (
            "sites", "location_types", "sensor_types", "variables", "sensor_models",
            "sensors", "locations", "location_labels", "deployments", "files", "interfaces",
        )},
    )
    document = SimpleNamespace(metadata=metadata)
    calls = {}
    monkeypatch.setattr(workbook, "get_target_environment", lambda: target_environment)

    def read(path, *, expected_environment):
        calls["read"] = (path, expected_environment)
        return document

    def parse(received_document):
        calls["parse"] = received_document
        return parsed

    def validate(received_parsed):
        calls["validate"] = received_parsed

    monkeypatch.setattr(workbook, "read_workbook", read)
    monkeypatch.setattr(workbook, "parse_workbook", parse)
    monkeypatch.setattr(workbook, "validate_workbook", validate)
    return calls, document, parsed


def test_workbook_validate_runs_offline_checks_and_reports_scope(
    monkeypatch, tmp_path, capsys,
):
    calls, document, parsed = install_validation_mocks(
        monkeypatch, scope="sites",
    )
    path = tmp_path / "sites.xlsx"

    assert main(["config", "workbook", "validate", str(path)]) == 0

    assert calls == {
        "read": (path, "local"),
        "parse": document,
        "validate": parsed,
    }
    report = capsys.readouterr().out
    assert "Workbook valid:" in report
    assert "Scope: sites" in report
    assert "Selected site IDs: 2, 3" in report
    assert "interfaces=0" in report


def test_workbook_validate_reports_located_issues(monkeypatch, tmp_path, capsys):
    from dendroflow.configuration.workbook.reader import (
        WorkbookIssue,
        WorkbookReadError,
    )

    monkeypatch.setattr(workbook, "get_target_environment", lambda: "local")
    monkeypatch.setattr(
        workbook,
        "read_workbook",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            WorkbookReadError((WorkbookIssue("sites", "A2", "bad site ID"),))
        ),
    )

    assert main(["config", "workbook", "validate", str(tmp_path / "bad.xlsx")]) == 2

    assert "sites!A2: bad site ID" in capsys.readouterr().err


def test_workbook_validate_needs_no_database_credentials(monkeypatch, tmp_path):
    from dendroflow import config

    monkeypatch.setattr(config, "load_env", lambda _path: {})
    monkeypatch.delenv("DENDROFLOW_ENVIRONMENT", raising=False)
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    metadata = SimpleNamespace(target_environment="local", scope="all", site_ids=())
    parsed = SimpleNamespace(
        metadata=metadata,
        frames={name: [] for name in (
            "sites", "location_types", "sensor_types", "variables", "sensor_models",
            "sensors", "locations", "location_labels", "deployments", "files", "interfaces",
        )},
    )
    monkeypatch.setattr(workbook, "read_workbook", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(workbook, "parse_workbook", lambda _document: parsed)
    monkeypatch.setattr(workbook, "validate_workbook", lambda _parsed: None)

    assert main(["config", "workbook", "validate", str(tmp_path / "ok.xlsx")]) == 0
