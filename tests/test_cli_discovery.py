import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from dendroflow.cli.main import main
from dendroflow.discovery import RegisteredFile


@pytest.fixture
def discovery_target(monkeypatch):
    target = SimpleNamespace(environment="local")
    monkeypatch.setattr(
        "dendroflow.cli.discovery.get_database_target",
        lambda: target,
    )
    monkeypatch.setattr(
        "dendroflow.cli.discovery.use_database_target",
        lambda selected: nullcontext(),
    )
    monkeypatch.setattr(
        "dendroflow.cli.discovery.get_registered_files",
        lambda: (),
    )
    return target


def test_discover_help_documents_scope_filters_and_json(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["discover", "--help"])

    assert caught.value.code == 0
    output = capsys.readouterr().out
    assert "--root PATH" in output
    assert "--recursive" in output
    assert "--include GLOB" in output
    assert "--exclude GLOB" in output
    assert "--json" in output


@pytest.mark.parametrize(
    "argv",
    [
        ["discover"],
        ["discover", "--root"],
    ],
)
def test_discover_requires_at_least_one_root(argv, capsys):
    with pytest.raises(SystemExit) as caught:
        main(argv)

    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage:" in captured.err


def test_discover_json_reports_file_states_and_target(
    tmp_path,
    discovery_target,
    monkeypatch,
    capsys,
):
    root = tmp_path / "sources"
    root.mkdir()
    registered_path = root / "registered.csv"
    registered_path.write_text("data", encoding="utf-8")
    unconfigured_path = root / "unconfigured.csv"
    unconfigured_path.write_text("data", encoding="utf-8")
    new_path = root / "new.csv"
    new_path.write_text("data", encoding="utf-8")
    monkeypatch.setattr(
        "dendroflow.cli.discovery.get_registered_files",
        lambda: (
            RegisteredFile(1, str(registered_path), 2),
            RegisteredFile(2, str(unconfigured_path), 0),
            RegisteredFile(3, str(root / "missing.csv"), 1),
        ),
    )

    assert main(["discover", "--root", str(root), "--json"]) == 1

    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert captured.err == ""
    assert document["schema_version"] == 1
    assert document["target_environment"] == "local"
    assert document["complete"] is True
    assert document["summary"] == {
        "total": 4,
        "unregistered": 1,
        "needs_configuration": 1,
        "registered": 1,
        "missing": 1,
    }
    assert {
        Path(item["path"]).name: (
            item["state"],
            item["file_id"],
            item["interface_count"],
        )
        for item in document["files"]
    } == {
        "registered.csv": ("registered", 1, 2),
        "unconfigured.csv": ("needs_configuration", 2, 0),
        "new.csv": ("unregistered", None, None),
        "missing.csv": ("missing", 3, 1),
    }
    assert document["scan_errors"] == []


def test_discover_text_reports_registered_file_and_returns_success(
    tmp_path,
    discovery_target,
    monkeypatch,
    capsys,
):
    root = tmp_path / "sources"
    root.mkdir()
    path = root / "registered.csv"
    path.write_text("data", encoding="utf-8")
    monkeypatch.setattr(
        "dendroflow.cli.discovery.get_registered_files",
        lambda: (RegisteredFile(8, str(path), 1),),
    )

    assert main(["discover", "--root", str(root)]) == 0

    captured = capsys.readouterr()
    assert "Target environment: local" in captured.out
    assert "Scan complete: true" in captured.out
    assert "State: registered" in captured.out
    assert "File ID: 8" in captured.out
    assert "Discovery summary: total=1, unregistered=0" in captured.out
    assert captured.err == ""


def test_discover_invalid_pattern_stops_before_database_read(
    tmp_path,
    discovery_target,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        "dendroflow.cli.discovery.get_registered_files",
        lambda: pytest.fail("database read started for an invalid pattern"),
    )

    assert main([
        "discover",
        "--root", str(tmp_path),
        "--include", r"bad\\pattern",
    ]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Invalid discovery request" in captured.err


def test_discover_database_error_returns_error_code(
    tmp_path,
    discovery_target,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        "dendroflow.cli.discovery.get_registered_files",
        lambda: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    assert main(["discover", "--root", str(tmp_path)]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Discovery comparison failed: database unavailable" in captured.err


def test_incomplete_scan_without_actionable_files_returns_three(
    tmp_path,
    discovery_target,
    monkeypatch,
    capsys,
):
    from dendroflow.discovery import scanner

    root = tmp_path / "sources"
    (root / "blocked").mkdir(parents=True)
    registered_path = root / "registered.csv"
    registered_path.write_text("data", encoding="utf-8")
    original_scandir = scanner.os.scandir

    def fail_for_blocked(path):
        if Path(path) == root / "blocked":
            raise PermissionError("access denied")
        return original_scandir(path)

    monkeypatch.setattr(scanner.os, "scandir", fail_for_blocked)
    monkeypatch.setattr(
        "dendroflow.cli.discovery.get_registered_files",
        lambda: (RegisteredFile(1, str(registered_path), 1),),
    )

    assert main([
        "discover", "--root", str(root), "--recursive", "--json",
    ]) == 3

    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert captured.err == ""
    assert document["complete"] is False
    assert document["files"][0]["state"] == "registered"
    assert len(document["scan_errors"]) == 1


def test_incomplete_scan_with_actionable_file_returns_one(
    tmp_path,
    discovery_target,
    monkeypatch,
    capsys,
):
    from dendroflow.discovery import scanner

    root = tmp_path / "sources"
    (root / "blocked").mkdir(parents=True)
    (root / "new.csv").write_text("data", encoding="utf-8")
    original_scandir = scanner.os.scandir

    def fail_for_blocked(path):
        if Path(path) == root / "blocked":
            raise PermissionError("access denied")
        return original_scandir(path)

    monkeypatch.setattr(scanner.os, "scandir", fail_for_blocked)

    assert main([
        "discover", "--root", str(root), "--recursive", "--json",
    ]) == 1

    document = json.loads(capsys.readouterr().out)
    assert document["complete"] is False
    assert any(item["state"] == "unregistered" for item in document["files"])
