import json
import os
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from dendroflow.cli.main import main
from dendroflow.database import connect
from dendroflow.discovery import registrations

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("DENDROFLOW_INTEGRATION") != "1",
        reason="Set DENDROFLOW_INTEGRATION=1 to run PostgreSQL integration tests",
    ),
]


@pytest.fixture
def discovery_case(tmp_path):
    tag = uuid4().hex
    paths = {
        "registered": tmp_path / f"registered_{tag}.csv",
        "unconfigured": tmp_path / f"unconfigured_{tag}.csv",
        "unregistered": tmp_path / f"unregistered_{tag}.csv",
        "temporary": tmp_path / "temporary" / f"ignored_{tag}.csv",
        "missing": tmp_path / f"missing_{tag}.csv",
        "nested_missing": tmp_path / "archive" / f"nested_missing_{tag}.csv",
    }
    for name in ("registered", "unconfigured", "unregistered", "temporary"):
        path = paths[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("header,value\n2026-01-01,1\n", encoding="utf-8")
    paths["nested_missing"].parent.mkdir(parents=True)

    file_ids = []
    try:
        with connect("dendroflow_raw") as connection:
            for name in ("registered", "unconfigured", "missing", "nested_missing"):
                file_id = connection.execute(
                    """
                    INSERT INTO files (
                        filepath,
                        timestamp_timezone,
                        timestamp_format,
                        reader_config
                    )
                    VALUES (%s, %s, %s, %s)
                    RETURNING file_id
                    """,
                    (
                        str(paths[name]),
                        "UTC",
                        "%Y-%m-%d",
                        Jsonb({"reader": "csv", "options": {}}),
                    ),
                ).fetchone()[0]
                file_ids.append(file_id)

                if name == "registered":
                    connection.execute(
                        """
                        INSERT INTO sensor_file_interfaces (
                            file_id,
                            deployment_id,
                            values_column,
                            timestamp_column,
                            unit
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (file_id, 1, "value", "header", "unit"),
                    )

        yield {"root": tmp_path, "paths": paths, "file_ids": tuple(file_ids)}
    finally:
        filepaths = [str(path) for path in paths.values()]
        with connect("dendroflow_raw") as connection:
            connection.execute(
                """
                DELETE FROM sensor_file_interfaces
                WHERE file_id = ANY(%s)
                   OR file_id IN (
                       SELECT file_id FROM files WHERE filepath = ANY(%s)
                   )
                """,
                (file_ids, filepaths),
            )
            connection.execute(
                "DELETE FROM files WHERE file_id = ANY(%s) OR filepath = ANY(%s)",
                (file_ids, filepaths),
            )


def _database_state(filepaths):
    filepaths = [str(path) for path in filepaths]
    with connect("dendroflow_raw") as connection:
        files = connection.execute(
            """
            SELECT file_id, filepath, xmin::text
            FROM files
            WHERE filepath = ANY(%s)
            ORDER BY file_id
            """,
            (filepaths,),
        ).fetchall()
        interfaces = connection.execute(
            """
            SELECT
                interface_id,
                file_id,
                deployment_id,
                values_column,
                timestamp_column,
                unit,
                xmin::text
            FROM sensor_file_interfaces
            WHERE file_id IN (
                SELECT file_id FROM files WHERE filepath = ANY(%s)
            )
            ORDER BY interface_id
            """,
            (filepaths,),
        ).fetchall()
    return tuple(files), tuple(interfaces)


def _run_discovery(root, capsys, *options):
    exit_code = main([
        "discover",
        "--root", str(root),
        *options,
        "--json",
    ])
    captured = capsys.readouterr()
    assert captured.err == ""
    return exit_code, json.loads(captured.out)


def test_discovery_cli_classifies_files_repeatably_without_writes(
    discovery_case,
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("DENDROFLOW_ENVIRONMENT", "local")
    root = discovery_case["root"]
    paths = discovery_case["paths"]
    file_ids = discovery_case["file_ids"]
    before_database = _database_state(paths.values())
    source_paths = tuple(
        paths[name]
        for name in ("registered", "unconfigured", "unregistered", "temporary")
    )
    before_sources = {
        path: (path.read_bytes(), path.stat().st_size, path.stat().st_mtime_ns)
        for path in source_paths
    }
    original_connect = registrations.connect
    connected_databases = []

    def record_discovery_database(database):
        connected_databases.append(database)
        return original_connect(database)

    monkeypatch.setattr(registrations, "connect", record_discovery_database)

    exit_code, report = _run_discovery(root, capsys, "--include", "*.csv")
    repeated_exit_code, repeated_report = _run_discovery(
        root,
        capsys,
        "--include", "*.csv",
    )

    assert exit_code == repeated_exit_code == 1
    assert report == repeated_report
    assert report["schema_version"] == 1
    assert report["target_environment"] == "local"
    assert report["complete"] is True
    assert report["summary"] == {
        "total": 4,
        "unregistered": 1,
        "needs_configuration": 1,
        "registered": 1,
        "missing": 1,
    }
    file_states = {
        item["path"]: (item["state"], item["file_id"], item["interface_count"])
        for item in report["files"]
    }
    assert file_states == {
        str(paths["registered"].resolve()): ("registered", file_ids[0], 1),
        str(paths["unconfigured"].resolve()): ("needs_configuration", file_ids[1], 0),
        str(paths["unregistered"].resolve()): ("unregistered", None, None),
        str(paths["missing"].resolve()): ("missing", file_ids[2], 0),
    }
    assert report["scan_errors"] == []

    recursive_exit_code, recursive_report = _run_discovery(
        root,
        capsys,
        "--recursive",
        "--include", "**/*.csv",
        "--exclude", "temporary/**",
    )
    assert recursive_exit_code == 1
    recursive_states = {
        item["path"]: item["state"]
        for item in recursive_report["files"]
    }
    assert recursive_states[str(paths["nested_missing"].resolve())] == "missing"
    assert str(paths["temporary"].resolve()) not in recursive_states

    assert _database_state(paths.values()) == before_database
    assert connected_databases == [
        "dendroflow_raw",
        "dendroflow_raw",
        "dendroflow_raw",
    ]
    assert {
        path: (path.read_bytes(), path.stat().st_size, path.stat().st_mtime_ns)
        for path in source_paths
    } == before_sources
