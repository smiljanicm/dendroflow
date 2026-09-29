"""Opt-in, isolated backup and restore acceptance drill."""

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import yaml
from psycopg import sql

from dendroflow.cli.main import main
from dendroflow.database import DATABASES, connect

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("DENDROFLOW_INTEGRATION") != "1"
        or os.getenv("DENDROFLOW_RECOVERY_DRILL") != "1",
        reason=(
            "Set DENDROFLOW_INTEGRATION=1 and DENDROFLOW_RECOVERY_DRILL=1 "
            "to run disposable Docker restore drill"
        ),
    ),
]

ROOT = Path(__file__).resolve().parents[2]


def _docker(*args, input_bytes=None):
    result = subprocess.run(
        ["docker", *args],
        input=input_bytes,
        capture_output=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


def _start_postgres(name, env_file):
    _docker(
        "run", "--detach", "--rm", "--name", name,
        "--env-file", str(env_file), "-p", "127.0.0.1::5432", "postgres:16",
    )
    port = int(_docker("port", name, "5432/tcp").decode().strip().rsplit(":", 1)[1])
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(
                host="127.0.0.1", port=port, user="dendroflow_test",
                password="recovery-test-only", dbname="postgres",
                connect_timeout=1,
            ):
                return port
        except psycopg.OperationalError:
            time.sleep(0.25)
    pytest.fail(f"Disposable PostgreSQL container {name} did not become ready")


def _create_databases(port):
    with psycopg.connect(
        host="127.0.0.1", port=port, user="dendroflow_test",
        password="recovery-test-only", dbname="postgres", autocommit=True,
    ) as admin:
        for database in DATABASES:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))


def _target(monkeypatch, port, snapshot_root):
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_PORT", str(port))
    monkeypatch.setenv("POSTGRES_USER", "dendroflow_test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "recovery-test-only")
    monkeypatch.setenv("DENDROFLOW_ENVIRONMENT", "local")
    monkeypatch.setenv("DENDROFLOW_ROOT", str(ROOT))
    monkeypatch.setenv("DENDROFLOW_SNAPSHOT_DIR", str(snapshot_root))
    monkeypatch.setenv("DENDROFLOW_FILE_SETTLE_SECONDS", "0")


def _config(source, tag):
    return {
        "sites": [{"ref": "site", "site_code": tag, "name": tag}],
        "location_types": [{"ref": "place", "type": tag}],
        "sensor_types": [{"ref": "kind", "type": tag}],
        "variables": [{"ref": "variable", "variable": tag}],
        "sensor_models": [{
            "ref": "model", "manufacturer": "Recovery drill",
            "model": tag, "sensor_type": "kind",
        }],
        "sensors": [{
            "ref": "sensor", "serial_number": tag, "sensor_model": "model",
        }],
        "locations": [{
            "ref": "location", "site": "site", "location_type": "place",
            "initial_label": {
                "label": "L1", "valid_from": "2026-01-01T00:00:00Z",
            },
        }],
        "deployments": [{
            "ref": "deployment", "sensor": "sensor", "location": "location",
            "variable": "variable", "valid_from": "2026-01-01T00:00:00Z",
        }],
        "files": [{
            "path": str(source),
            "timestamp": {"timezone": "UTC", "format": "%Y-%m-%d %H:%M:%S"},
            "reader": {"type": "csv", "options": {}},
            "interfaces": [{
                "deployment": "deployment", "timestamp_column": "TIMESTAMP",
                "values_column": "value", "unit": "cm",
            }],
        }],
    }


def _state():
    """Capture IDs, relationships, content, provenance and migration history."""
    state = {}
    for database in DATABASES:
        with connect(database) as connection:
            state[database + "_migrations"] = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()

    with connect("dendroflow_metadata") as connection:
        state["sites"] = connection.execute(
            "SELECT site_id, site_code, name FROM sites ORDER BY site_id"
        ).fetchall()
        state["deployments"] = connection.execute(
            "SELECT deployment_id, sensor_id, location_id, variable_id "
            "FROM deployments ORDER BY deployment_id"
        ).fetchall()
    with connect("dendroflow_raw") as connection:
        state["files"] = connection.execute(
            "SELECT file_id, filepath FROM files ORDER BY file_id"
        ).fetchall()
        state["versions"] = connection.execute(
            "SELECT file_version_id, file_id, file_hash, file_size "
            "FROM file_versions ORDER BY file_version_id"
        ).fetchall()
        state["interfaces"] = connection.execute(
            "SELECT interface_id, deployment_id FROM sensor_file_interfaces "
            "ORDER BY interface_id"
        ).fetchall()
        state["runs"] = connection.execute(
            "SELECT ingestion_run_id, status FROM ingestion_runs "
            "ORDER BY ingestion_run_id"
        ).fetchall()
        state["observations"] = connection.execute(
            "SELECT observation_id, location_id, variable_id, timestamp, value, "
            "interface_id, ingestion_run_id, source_row_number "
            "FROM raw_observations ORDER BY observation_id"
        ).fetchall()
    with connect("dendroflow_clean") as connection:
        state["datasets"] = connection.execute(
            "SELECT clean_dataset_id, name FROM clean_datasets ORDER BY clean_dataset_id"
        ).fetchall()
        state["clean_observations"] = connection.execute(
            "SELECT clean_observation_id, clean_dataset_id, location_id, "
            "variable_id, timestamp, value, quality_status "
            "FROM clean_observations ORDER BY clean_observation_id"
        ).fetchall()
        state["inputs"] = connection.execute(
            "SELECT clean_observation_id, raw_observation_id "
            "FROM clean_observation_inputs ORDER BY clean_observation_id"
        ).fetchall()
    return state


def _assert_cli(capsys, *args):
    result = main(list(args))
    output = capsys.readouterr()
    assert result == 0, output.out + output.err
    return output.out


def test_backup_restore_all_databases_and_file_assets(tmp_path, monkeypatch, capsys):
    assert shutil.which("docker"), "Recovery drill requires Docker and postgres:16"
    tag = uuid4().hex
    original = f"dendroflow-recovery-source-{tag}"
    restored = f"dendroflow-recovery-restored-{tag}"
    env_file = tmp_path / "postgres.env"
    env_file.write_text(
        "POSTGRES_USER=dendroflow_test\n"
        "POSTGRES_PASSWORD=recovery-test-only\n"
        "POSTGRES_DB=postgres\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    started = []
    snapshot_root = tmp_path / "snapshots"
    source = tmp_path / "source.csv"
    config_path = tmp_path / "config.yaml"
    backup = tmp_path / "backup"
    backup.mkdir()

    try:
        started.append(original)
        source_port = _start_postgres(original, env_file)
        _create_databases(source_port)
        _target(monkeypatch, source_port, snapshot_root)
        _assert_cli(capsys, "migrate")

        source.write_text(
            "TIMESTAMP,value\n"
            "2026-01-02 00:00:00,10.0\n"
            "2026-01-02 00:15:00,11.0\n",
            encoding="utf-8",
        )
        config_path.write_text(
            yaml.safe_dump(_config(source, tag), sort_keys=False),
            encoding="utf-8",
        )
        _assert_cli(capsys, "config", "apply", str(config_path), "--yes")
        first = json.loads(_assert_cli(capsys, "ingest", "--all", "--json"))
        assert first["files"][0]["outcome"] == "completed"

        initial = _state()
        assert len(initial["observations"]) == 2
        assert initial["interfaces"][0][1] == initial["deployments"][0][0]
        with connect("dendroflow_clean") as connection:
            dataset_id = connection.execute(
                "INSERT INTO clean_datasets (name) VALUES (%s) "
                "RETURNING clean_dataset_id", (tag,),
            ).fetchone()[0]
            observation = initial["observations"][0]
            clean_id = connection.execute(
                "INSERT INTO clean_observations (clean_dataset_id, location_id, "
                "variable_id, timestamp, value, quality_status) "
                "VALUES (%s, %s, %s, %s, %s, 'valid') "
                "RETURNING clean_observation_id",
                (dataset_id, observation[1], observation[2],
                 observation[3], observation[4]),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO clean_observation_inputs "
                "(clean_observation_id, raw_observation_id) VALUES (%s, %s)",
                (clean_id, observation[0]),
            )
        expected = _state()
        assert expected["inputs"] == [(clean_id, observation[0])]

        file_id = expected["files"][0][0]
        version = expected["versions"][0]
        digest = version[2].removeprefix("sha256:")
        staged = snapshot_root / str(file_id) / f"{digest}.snapshot"
        assert staged.read_bytes() == source.read_bytes()
        shutil.copy2(source, backup / "source.csv")
        shutil.copy2(config_path, backup / "config.yaml")
        shutil.copytree(snapshot_root, backup / "snapshots")
        for database in DATABASES:
            (backup / f"{database}.dump").write_bytes(
                _docker("exec", original, "pg_dump", "-U", "dendroflow_test",
                        "-d", database, "-Fc", "--no-owner", "--no-acl")
            )

        _docker("stop", original)
        started.remove(original)
        source.unlink()
        config_path.unlink()
        shutil.rmtree(snapshot_root)

        started.append(restored)
        restore_port = _start_postgres(restored, env_file)
        _create_databases(restore_port)
        for database in DATABASES:
            _docker(
                "exec", "-i", restored, "pg_restore", "-U", "dendroflow_test",
                "-d", database, "--no-owner", "--no-acl", "--exit-on-error",
                input_bytes=(backup / f"{database}.dump").read_bytes(),
            )
        shutil.copy2(backup / "source.csv", source)
        shutil.copy2(backup / "config.yaml", config_path)
        shutil.copytree(backup / "snapshots", snapshot_root)
        _target(monkeypatch, restore_port, snapshot_root)

        assert _state() == expected
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
        assert staged.read_bytes() == source.read_bytes()
        assert expected["interfaces"][0][1] == expected["deployments"][0][0]
        assert expected["inputs"][0][1] == expected["observations"][0][0]

        assert _assert_cli(capsys, "migrate").count("No pending migrations") == 3
        replay = json.loads(_assert_cli(capsys, "ingest", "--all", "--json"))
        assert replay["files"][0]["outcome"] == "already_completed"
        assert _state() == expected

        with source.open("a", encoding="utf-8") as target:
            target.write("2026-01-02 00:30:00,12.0\n")
        appended = json.loads(_assert_cli(capsys, "ingest", "--all", "--json"))
        assert appended["files"][0]["outcome"] == "completed"
        assert appended["files"][0]["counts"]["observations_inserted"] == 1
        after = _state()
        assert len(after["observations"]) == 3
        assert after["observations"][:2] == expected["observations"]
    finally:
        for name in reversed(started):
            subprocess.run(
                ["docker", "stop", name], check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
            )
