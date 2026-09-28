from pathlib import Path

import pytest

from dendroflow import migrations


def test_migrations_are_read_from_installed_package_outside_checkout(
    tmp_path,
    monkeypatch,
):
    package = tmp_path / "site-packages" / "dendroflow"
    sql_directory = package / "sql" / "raw" / "migrations"
    sql_directory.mkdir(parents=True)
    (sql_directory / "001_initial.sql").write_text("SELECT 1;")
    unrelated_directory = tmp_path / "elsewhere"
    unrelated_directory.mkdir()

    monkeypatch.chdir(unrelated_directory)
    monkeypatch.delenv("DENDROFLOW_ROOT", raising=False)
    monkeypatch.setattr(migrations, "__file__", str(package / "migrations.py"))

    files = migrations.get_migration_files("dendroflow_raw")
    assert [path.read_text() for path in files] == ["SELECT 1;"]


def test_explicit_migration_root_must_exist(tmp_path, monkeypatch):
    configured_root = tmp_path / "configured"
    monkeypatch.setenv("DENDROFLOW_ROOT", str(configured_root))
    assert migrations.get_migrations_directory("dendroflow_raw") == (
        configured_root / "db" / "raw" / "migrations"
    )
    with pytest.raises(RuntimeError, match="Migration directory does not exist"):
        migrations.get_migration_files("dendroflow_raw")


def test_checkout_migrations_are_preferred_when_running_from_checkout(
    tmp_path,
    monkeypatch,
):
    checkout = tmp_path / "checkout"
    migrations_directory = checkout / "db" / "metadata" / "migrations"
    migrations_directory.mkdir(parents=True)
    (migrations_directory / "001_initial.sql").write_text("SELECT 2;")

    monkeypatch.chdir(checkout)
    monkeypatch.delenv("DENDROFLOW_ROOT", raising=False)

    assert migrations.get_migration_files("dendroflow_metadata") == [
        Path("db/metadata/migrations/001_initial.sql").absolute()
    ]
