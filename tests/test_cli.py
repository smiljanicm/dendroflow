import runpy
import sys

import pytest

import dendroflow.cli.main as cli


@pytest.fixture(autouse=True)
def block_real_migrations(monkeypatch):
    def unexpected_migration(database):
        pytest.fail(f"Unexpected migration call: {database}")

    monkeypatch.setattr(cli, "migrate_database", unexpected_migration)


@pytest.mark.parametrize("argv", [["--help"], ["migrate", "--help"]])
def test_help_does_not_run_migrations(argv, capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(argv)

    assert caught.value.code == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out
    assert "migrate" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["unknown"],
        ["migrate", "unexpected"],
        ["migrate", "--unknown"],
    ],
)
def test_invalid_arguments_do_not_run_migrations(argv, capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(argv)

    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage:" in captured.err
    assert "error:" in captured.err


def test_migrate_reports_applied_versions(monkeypatch, capsys):
    calls = []
    versions = {
        "dendroflow_metadata": ["001_initial.sql", "002_change.sql"],
        "dendroflow_raw": [],
        "dendroflow_clean": ["001_initial.sql"],
    }

    def fake_migrate(database):
        calls.append(database)
        return versions[database]

    monkeypatch.setattr(cli, "migrate_database", fake_migrate)

    assert cli.main(["migrate"]) == 0
    assert calls == [
        "dendroflow_metadata",
        "dendroflow_raw",
        "dendroflow_clean",
    ]
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "Migrating dendroflow_metadata...",
        "  Applied 001_initial.sql",
        "  Applied 002_change.sql",
        "Migrating dendroflow_raw...",
        "  No pending migrations",
        "Migrating dendroflow_clean...",
        "  Applied 001_initial.sql",
        "Migration complete.",
    ]
    assert captured.err == ""


def test_migrate_reports_no_pending_migrations(monkeypatch, capsys):
    calls = []

    def fake_migrate(database):
        calls.append(database)
        return []

    monkeypatch.setattr(cli, "migrate_database", fake_migrate)

    assert cli.main(["migrate"]) == 0
    assert calls == list(cli.DATABASES)
    captured = capsys.readouterr()
    assert captured.out.count("No pending migrations") == 3
    assert captured.out.endswith("Migration complete.\n")
    assert captured.err == ""


@pytest.mark.parametrize("failed_index", [0, 1, 2])
def test_migrate_stops_at_first_failure(
    failed_index,
    monkeypatch,
    capsys,
):
    calls = []
    failed_database = cli.DATABASES[failed_index]

    def fake_migrate(database):
        calls.append(database)
        if database == failed_database:
            raise RuntimeError("migration unavailable")
        return []

    monkeypatch.setattr(cli, "migrate_database", fake_migrate)

    assert cli.main(["migrate"]) == 1
    assert calls == list(cli.DATABASES[:failed_index + 1])
    captured = capsys.readouterr()
    assert "Migration complete." not in captured.out
    assert captured.err == (
        f"  Migration failed for {failed_database}: "
        "migration unavailable\n"
    )


@pytest.mark.parametrize(
    ("argv", "expected_code"),
    [
        (["--help"], 0),
        (["unknown"], 2),
    ],
)
def test_module_entry_point(argv, expected_code, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["dendroflow", *argv])

    with pytest.raises(SystemExit) as caught:
        runpy.run_module("dendroflow", run_name="__main__")

    assert caught.value.code == expected_code


def test_module_entry_point_propagates_command_failure(monkeypatch):
    def fail_migration(database):
        raise RuntimeError("migration unavailable")

    monkeypatch.setattr(cli, "migrate_database", fail_migration)
    monkeypatch.setattr(sys, "argv", ["dendroflow", "migrate"])

    with pytest.raises(SystemExit) as caught:
        runpy.run_module("dendroflow", run_name="__main__")

    assert caught.value.code == 1
    