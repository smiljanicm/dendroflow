"""Exercise the migration CLI against isolated, initially empty databases."""

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from dendroflow import migrations
from dendroflow.cli.main import main
from dendroflow.config import get_connection_parameters
from dendroflow.database import DATABASES

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("DENDROFLOW_INTEGRATION") != "1"
        or os.getenv("DENDROFLOW_FRESH_MIGRATION") != "1",
        reason=(
            "Set DENDROFLOW_INTEGRATION=1 and DENDROFLOW_FRESH_MIGRATION=1 "
            "on a disposable PostgreSQL instance"
        ),
    ),
]

EXPECTED_TABLE = {
    "dendroflow_metadata": "deployments",
    "dendroflow_raw": "raw_observations",
    "dendroflow_clean": "clean_observations",
}


def test_migrate_empty_databases_twice(monkeypatch, capsys):
    """The CLI installs each schema and a second run applies nothing."""
    parameters = get_connection_parameters()
    suffix = uuid4().hex
    database_names = {
        database: f"dendroflow_mvp2b_{database.removeprefix('dendroflow_')}_{suffix}"
        for database in DATABASES
    }
    created = []

    # CREATE/DROP DATABASE cannot run in a PostgreSQL transaction.
    with psycopg.connect(dbname="postgres", autocommit=True, **parameters) as admin:
        try:
            for database_name in database_names.values():
                admin.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
                )
                created.append(database_name)

            def connect_disposable(database):
                return psycopg.connect(
                    dbname=database_names[database], **parameters
                )

            monkeypatch.setattr(migrations, "connect", connect_disposable)

            for database in DATABASES:
                with connect_disposable(database) as connection:
                    assert connection.execute(
                        "SELECT to_regclass('public.schema_migrations')"
                    ).fetchone()[0] is None

            assert main(["migrate"]) == 0
            first_output = capsys.readouterr()
            assert not first_output.err

            for database in DATABASES:
                expected_versions = {
                    path.name for path in migrations.get_migration_files(database)
                }
                assert expected_versions
                with connect_disposable(database) as connection:
                    actual_versions = {
                        row[0] for row in connection.execute(
                            "SELECT version FROM schema_migrations"
                        ).fetchall()
                    }
                    assert actual_versions == expected_versions
                    assert connection.execute(
                        "SELECT to_regclass(%s)",
                        (f"public.{EXPECTED_TABLE[database]}",),
                    ).fetchone()[0] is not None

            assert main(["migrate"]) == 0
            second_output = capsys.readouterr()
            assert not second_output.err
            assert second_output.out.count("No pending migrations") == len(DATABASES)

            for database in DATABASES:
                with connect_disposable(database) as connection:
                    count = connection.execute(
                        "SELECT COUNT(*) FROM schema_migrations"
                    ).fetchone()[0]
                    assert count == len(migrations.get_migration_files(database))
        finally:
            for database_name in reversed(created):
                admin.execute(
                    sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name))
                )
