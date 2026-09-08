from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import pandas as pd
import hashlib
import pytest

from dendroflow.tabular import TabularBatch

from dendroflow.ingestion import (
    validate_ingestion_batch_checkpoint,
    get_ingestion_batch,
    get_resumable_ingestion_run,
    create_ingestion_run_with_targets,
    ingest_file,
    finalize_ingestion_run,
    insert_raw_observations,
    write_ingestion_batch,
    IngestionBatch,
    complete_ingestion_batch,
    create_ingestion_batch,
    fail_ingestion_batch,
    start_ingestion_batch,
    IngestionRun,
    create_ingestion_run,
    finish_ingestion_run,
    Deployment,
    NormalizedObservation,
    SourceFile,
    SourceInterface,
    get_deployments,
    get_source_interfaces,
    normalize_batch,
    read_source_file,
    fingerprint_file,
    FileFingerprint,
    get_or_create_file_version,
    FileVersion,
)

def test_create_ingestion_run(monkeypatch):
    started_at = datetime(
        2026,
        9,
        6,
        18,
        30,
        tzinfo=timezone.utc,
    )

    class FakeResult:
        def fetchone(self):
            return (
                7,
                started_at,
                None,
                "running",
            )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def execute(self, query):
            return FakeResult()

    monkeypatch.setattr(
        "dendroflow.ingestion.runs.connect",
        lambda database: FakeConnection(),
    )

    run = create_ingestion_run()

    assert run == IngestionRun(
        ingestion_run_id=7,
        started_at=started_at,
        finished_at=None,
        status="running",
    )

def test_finish_ingestion_run(monkeypatch):
    started_at = datetime(
        2026,
        9,
        6,
        18,
        30,
        tzinfo=timezone.utc,
    )

    finished_at = datetime(
        2026,
        9,
        6,
        18,
        31,
        tzinfo=timezone.utc,
    )

    class FakeResult:
        def fetchone(self):
            return (
                7,
                started_at,
                finished_at,
                "completed",
            )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def execute(self, query, parameters):
            assert parameters == (
                "completed",
                7,
            )

            return FakeResult()

    monkeypatch.setattr(
        "dendroflow.ingestion.runs.connect",
        lambda database: FakeConnection(),
    )

    run = finish_ingestion_run(
        7,
        "completed",
    )

    assert run.status == "completed"
    assert run.finished_at == finished_at

def test_finish_ingestion_run_rejects_running_status():
    with pytest.raises(ValueError):
        finish_ingestion_run(1, "running")

def test_create_ingestion_batch(monkeypatch):
    class FakeResult:
        def fetchone(self):
            return (
                1,      # ingestion_batch_id
                7,      # ingestion_run_id
                3,      # file_version_id
                1,      # batch_number
                5,      # source_line_start
                104,    # source_line_end
                100,    # row_count
                "pending",
                0,      # attempt_count
                None,   # started_at
                None,   # finished_at
                None,   # error_message
            )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def execute(self, query, parameters):
            assert parameters == (
                7,
                3,
                1,
                5,
                104,
                100,
            )
            return FakeResult()

    monkeypatch.setattr(
        "dendroflow.ingestion.batches.connect",
        lambda database: FakeConnection(),
    )

    batch = create_ingestion_batch(
        ingestion_run_id=7,
        file_version_id=3,
        batch_number=1,
        source_line_start=5,
        source_line_end=104,
        row_count=100,
    )

    assert batch.status == "pending"
    assert batch.attempt_count == 0
    assert batch.source_line_start == 5
    assert batch.source_line_end == 104
    assert batch.row_count == 100

def test_start_ingestion_batch(monkeypatch):
    started_at = datetime(
        2026,
        9,
        7,
        12,
        0,
        tzinfo=timezone.utc,
    )

    class FakeResult:
        def fetchone(self):
            return (
                1,
                7,
                3,
                1,
                5,
                104,
                100,
                "running",
                1,
                started_at,
                None,
                None,
            )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def execute(self, query, parameters):
            assert parameters == (1,)
            return FakeResult()

    monkeypatch.setattr(
        "dendroflow.ingestion.batches.connect",
        lambda database: FakeConnection(),
    )

    batch = start_ingestion_batch(1)

    assert batch.status == "running"
    assert batch.attempt_count == 1
    assert batch.started_at == started_at
    assert batch.finished_at is None

def test_fail_ingestion_batch(monkeypatch):
    started_at = datetime(
        2026,
        9,
        7,
        12,
        0,
        tzinfo=timezone.utc,
    )

    finished_at = datetime(
        2026,
        9,
        7,
        12,
        1,
        tzinfo=timezone.utc,
    )

    class FakeResult:
        def fetchone(self):
            return (
                1,
                7,
                3,
                1,
                5,
                104,
                100,
                "failed",
                1,
                started_at,
                finished_at,
                "Database connection lost",
            )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def execute(self, query, parameters):
            assert parameters == (
                "Database connection lost",
                1,
            )
            return FakeResult()

    monkeypatch.setattr(
        "dendroflow.ingestion.batches.connect",
        lambda database: FakeConnection(),
    )

    batch = fail_ingestion_batch(
        1,
        "Database connection lost",
    )

    assert batch.status == "failed"
    assert batch.attempt_count == 1
    assert batch.finished_at == finished_at
    assert batch.error_message == "Database connection lost"

def test_complete_ingestion_batch():
    started_at = datetime(
        2026,
        9,
        7,
        12,
        0,
        tzinfo=timezone.utc,
    )

    finished_at = datetime(
        2026,
        9,
        7,
        12,
        1,
        tzinfo=timezone.utc,
    )

    class FakeResult:
        def fetchone(self):
            return (
                1,
                7,
                3,
                1,
                5,
                104,
                100,
                "completed",
                1,
                started_at,
                finished_at,
                None,
            )

    class FakeConnection:
        def execute(self, query, parameters):
            assert parameters == (1,)
            return FakeResult()

    connection = FakeConnection()

    batch = complete_ingestion_batch(
        connection,
        1,
    )

    assert batch.status == "completed"
    assert batch.attempt_count == 1
    assert batch.finished_at == finished_at
    assert batch.error_message is None

def test_insert_raw_observations():
    timestamp_1 = datetime(
        2026, 3, 19, 12, 15,
        tzinfo=timezone.utc,
    )

    timestamp_2 = datetime(
        2026, 3, 19, 12, 30,
        tzinfo=timezone.utc,
    )

    observations = (
        NormalizedObservation(
            location_id=3,
            variable_id=1,
            timestamp=timestamp_1,
            value=10.5,
            interface_id=4,
            source_row_number=5,
        ),
        NormalizedObservation(
            location_id=3,
            variable_id=1,
            timestamp=timestamp_2,
            value=11.2,
            interface_id=4,
            source_row_number=6,
        ),
    )

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def executemany(self, query, rows):
            self.rows = rows

            assert rows == [
                (
                    3,
                    1,
                    timestamp_1,
                    10.5,
                    4,
                    7,
                    5,
                ),
                (
                    3,
                    1,
                    timestamp_2,
                    11.2,
                    4,
                    7,
                    6,
                ),
            ]

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    insert_raw_observations(
        FakeConnection(),
        ingestion_run_id=7,
        observations=observations,
    )

def test_write_ingestion_batch_uses_one_transaction(
    monkeypatch,
):
    connection = object()

    batch = IngestionBatch(
        ingestion_batch_id=1,
        ingestion_run_id=7,
        file_version_id=3,
        batch_number=1,
        source_line_start=5,
        source_line_end=6,
        row_count=2,
        status="running",
        attempt_count=1,
        started_at=datetime.now(timezone.utc),
        finished_at=None,
        error_message=None,
    )

    observations = (
        NormalizedObservation(
            location_id=3,
            variable_id=1,
            timestamp=datetime.now(timezone.utc),
            value=10.5,
            interface_id=1,
            source_row_number=5,
        ),
    )

    class FakeConnectionContext:
        def __enter__(self):
            return connection

        def __exit__(self, exc_type, exc_value, traceback):
            pass

    monkeypatch.setattr(
        "dendroflow.ingestion.writer.connect",
        lambda database: FakeConnectionContext(),
    )

    def fake_insert(
        received_connection,
        ingestion_run_id,
        received_observations,
    ):
        assert received_connection is connection
        assert ingestion_run_id == 7
        assert received_observations is observations

    monkeypatch.setattr(
        "dendroflow.ingestion.writer.insert_raw_observations",
        fake_insert,
    )

    completed_batch = IngestionBatch(
        **{
            **batch.__dict__,
            "status": "completed",
            "finished_at": datetime.now(timezone.utc),
        }
    )

    def fake_complete(
        received_connection,
        ingestion_batch_id,
    ):
        assert received_connection is connection
        assert ingestion_batch_id == 1
        return completed_batch

    monkeypatch.setattr(
        "dendroflow.ingestion.writer.complete_ingestion_batch",
        fake_complete,
    )

    result = write_ingestion_batch(
        batch,
        observations,
    )

    assert result.status == "completed"

def test_write_ingestion_batch_rejects_non_running_batch():
    batch = IngestionBatch(
        ingestion_batch_id=1,
        ingestion_run_id=7,
        file_version_id=3,
        batch_number=1,
        source_line_start=5,
        source_line_end=6,
        row_count=2,
        status="pending",
        attempt_count=0,
        started_at=None,
        finished_at=None,
        error_message=None,
    )

    observation = NormalizedObservation(
        location_id=3,
        variable_id=1,
        timestamp=datetime.now(timezone.utc),
        value=10.5,
        interface_id=1,
        source_row_number=5,
    )

    with pytest.raises(
        ValueError,
        match="must be running",
    ):
        write_ingestion_batch(
            batch,
            (observation,),
        )

def test_finalize_ingestion_run(monkeypatch):
    started_at = datetime(
        2026,
        9,
        7,
        12,
        0,
        tzinfo=timezone.utc,
    )

    finished_at = datetime(
        2026,
        9,
        7,
        12,
        5,
        tzinfo=timezone.utc,
    )

    interfaces = (
        SourceInterface(
            interface_id=1,
            file_id=1,
            deployment_id=101,
            values_column="temperature",
            timestamp_column="TIMESTAMP",
            unit="deg C",
        ),
        SourceInterface(
            interface_id=2,
            file_id=1,
            deployment_id=102,
            values_column="water_level",
            timestamp_column="TIMESTAMP",
            unit="cm",
        ),
    )

    class BatchCountResult:
        def fetchone(self):
            return (3, 0)

    class RunResult:
        def fetchone(self):
            return (
                7,
                started_at,
                finished_at,
                "completed",
            )

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def executemany(self, query, rows):
            assert rows == [
                (7, 3, 1),
                (7, 3, 2),
            ]

    class FakeConnection:
        def __init__(self):
            self.execute_count = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def cursor(self):
            return FakeCursor()

        def execute(self, query, parameters):
            self.execute_count += 1

            if self.execute_count == 1:
                assert parameters == (7,)
                return BatchCountResult()

            assert parameters == (7,)
            return RunResult()

    monkeypatch.setattr(
        "dendroflow.ingestion.runs.connect",
        lambda database: FakeConnection(),
    )

    run = finalize_ingestion_run(
        ingestion_run_id=7,
        file_version_id=3,
        interfaces=interfaces,
    )

    assert run.status == "completed"
    assert run.finished_at == finished_at

def test_finalize_ingestion_run_rejects_incomplete_batches(
    monkeypatch,
):
    interface = SourceInterface(
        interface_id=1,
        file_id=1,
        deployment_id=101,
        values_column="temperature",
        timestamp_column="TIMESTAMP",
        unit="deg C",
    )

    class BatchCountResult:
        def fetchone(self):
            return (
                3,  # total
                1,  # incomplete
            )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def execute(self, query, parameters):
            return BatchCountResult()

    monkeypatch.setattr(
        "dendroflow.ingestion.runs.connect",
        lambda database: FakeConnection(),
    )

    with pytest.raises(
        ValueError,
        match="incomplete batches",
    ):
        finalize_ingestion_run(
            ingestion_run_id=7,
            file_version_id=3,
            interfaces=(interface,),
        )

def test_finalize_ingestion_run_rejects_run_without_batches(
    monkeypatch,
):
    interface = SourceInterface(
        interface_id=1,
        file_id=1,
        deployment_id=101,
        values_column="temperature",
        timestamp_column="TIMESTAMP",
        unit="deg C",
    )

    class BatchCountResult:
        def fetchone(self):
            return (0, 0)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def execute(self, query, parameters):
            return BatchCountResult()

    monkeypatch.setattr(
        "dendroflow.ingestion.runs.connect",
        lambda database: FakeConnection(),
    )

    with pytest.raises(
        ValueError,
        match="has no batches",
    ):
        finalize_ingestion_run(
            ingestion_run_id=7,
            file_version_id=3,
            interfaces=(interface,),
        )

def test_ingest_file(monkeypatch, tmp_path):
    source_file = SourceFile(
        file_id=1,
        filepath=tmp_path / "example.csv",
        timestamp_timezone="UTC",
        timestamp_format="%Y-%m-%d %H:%M:%S",
        reader_config={},
    )

    fingerprint = FileFingerprint(
        file_hash="sha256:test",
        file_size=100,
    )

    file_version = FileVersion(
        file_version_id=3,
        file_id=1,
        file_hash="sha256:test",
        file_size=100,
    )

    interface = SourceInterface(
        interface_id=4,
        file_id=1,
        deployment_id=10,
        values_column="value",
        timestamp_column="TIMESTAMP",
        unit="cm",
    )

    deployment = Deployment(
        deployment_id=10,
        sensor_id=1,
        location_id=2,
        variable_id=3,
        valid_from=datetime(
            2025,
            1,
            1,
            tzinfo=timezone.utc,
        ),
        valid_to=None,
    )

    tabular_batch = TabularBatch(
        dataframe=pd.DataFrame(
            {
                "TIMESTAMP": [
                    "2026-01-01 12:00:00",
                ],
                "value": [
                    10.5,
                ],
            }
        ),
        source_line_numbers=(2,),
    )

    run = IngestionRun(
        ingestion_run_id=7,
        started_at=datetime.now(timezone.utc),
        finished_at=None,
        status="running",
    )

    pending_batch = IngestionBatch(
        ingestion_batch_id=8,
        ingestion_run_id=7,
        file_version_id=3,
        batch_number=1,
        source_line_start=2,
        source_line_end=2,
        row_count=1,
        status="pending",
        attempt_count=0,
        started_at=None,
        finished_at=None,
        error_message=None,
    )

    running_batch = IngestionBatch(
        **{
            **pending_batch.__dict__,
            "status": "running",
            "attempt_count": 1,
            "started_at": datetime.now(timezone.utc),
        }
    )

    completed_batch = IngestionBatch(
        **{
            **running_batch.__dict__,
            "status": "completed",
            "finished_at": datetime.now(timezone.utc),
        }
    )

    completed_run = IngestionRun(
        ingestion_run_id=7,
        started_at=run.started_at,
        finished_at=datetime.now(timezone.utc),
        status="completed",
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_source_file",
        lambda file_id: source_file,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.fingerprint_file",
        lambda path: fingerprint,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_or_create_file_version",
        lambda file_id, fingerprint: file_version,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_source_interfaces",
        lambda file_id: (interface,),
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_deployments",
        lambda deployment_ids: {10: deployment},
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.create_ingestion_run_with_targets",
        lambda file_version_id, interfaces: run,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.read_source_file",
        lambda file_id: iter((tabular_batch,)),
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.create_ingestion_batch",
        lambda **kwargs: pending_batch,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.start_ingestion_batch",
        lambda ingestion_batch_id: running_batch,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.write_ingestion_batch",
        lambda batch, observations: completed_batch,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.finalize_ingestion_run",
        lambda **kwargs: completed_run,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_resumable_ingestion_run",
        lambda file_version_id, interface_ids: None,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_ingestion_batch",
        lambda ingestion_run_id, file_version_id, batch_number: None,
    )

    result = ingest_file(1)

    assert result.status == "completed"
    assert result.ingestion_run_id == 7

def test_ingest_file_retries_failed_batch(
    monkeypatch,
    tmp_path,
):
    source_file = SourceFile(
        file_id=1,
        filepath=tmp_path / "example.csv",
        timestamp_timezone="UTC",
        timestamp_format="%Y-%m-%d %H:%M:%S",
        reader_config={},
    )

    interface = SourceInterface(
        interface_id=1,
        file_id=1,
        deployment_id=10,
        values_column="value",
        timestamp_column="TIMESTAMP",
        unit="cm",
    )

    deployment = Deployment(
        deployment_id=10,
        sensor_id=1,
        location_id=2,
        variable_id=3,
        valid_from=datetime(
            2025,
            1,
            1,
            tzinfo=timezone.utc,
        ),
        valid_to=None,
    )

    tabular_batch = TabularBatch(
        dataframe=pd.DataFrame(
            {
                "TIMESTAMP": [
                    "2026-01-01 12:00:00",
                ],
                "value": [
                    10.5,
                ],
            }
        ),
        source_line_numbers=(2,),
    )

    now = datetime.now(timezone.utc)

    run = IngestionRun(
        ingestion_run_id=7,
        started_at=now,
        finished_at=None,
        status="running",
    )

    pending = IngestionBatch(
        ingestion_batch_id=8,
        ingestion_run_id=7,
        file_version_id=3,
        batch_number=1,
        source_line_start=2,
        source_line_end=2,
        row_count=1,
        status="pending",
        attempt_count=0,
        started_at=None,
        finished_at=None,
        error_message=None,
    )

    running_1 = IngestionBatch(
        **{
            **pending.__dict__,
            "status": "running",
            "attempt_count": 1,
            "started_at": now,
        }
    )

    failed = IngestionBatch(
        **{
            **running_1.__dict__,
            "status": "failed",
            "finished_at": now,
            "error_message": "RuntimeError: temporary failure",
        }
    )

    running_2 = IngestionBatch(
        **{
            **failed.__dict__,
            "status": "running",
            "attempt_count": 2,
            "started_at": now,
            "finished_at": None,
            "error_message": None,
        }
    )

    completed = IngestionBatch(
        **{
            **running_2.__dict__,
            "status": "completed",
            "finished_at": now,
        }
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_source_file",
        lambda file_id: source_file,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.fingerprint_file",
        lambda path: FileFingerprint(
            file_hash="sha256:test",
            file_size=100,
        ),
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_or_create_file_version",
        lambda *args: FileVersion(
            file_version_id=3,
            file_id=1,
            file_hash="sha256:test",
            file_size=100,
        ),
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_source_interfaces",
        lambda file_id: (interface,),
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_deployments",
        lambda ids: {10: deployment},
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.create_ingestion_run_with_targets",
        lambda file_version_id, interfaces: run,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.read_source_file",
        lambda file_id: iter((tabular_batch,)),
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.create_ingestion_batch",
        lambda **kwargs: pending,
    )

    starts = iter((running_1, running_2))

    monkeypatch.setattr(
        "dendroflow.ingestion.service.start_ingestion_batch",
        lambda batch_id: next(starts),
    )

    writes = {"count": 0}

    def fake_write(batch, observations):
        writes["count"] += 1

        if writes["count"] == 1:
            raise RuntimeError("temporary failure")

        return completed

    monkeypatch.setattr(
        "dendroflow.ingestion.service.write_ingestion_batch",
        fake_write,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.fail_ingestion_batch",
        lambda batch_id, error: failed,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.finalize_ingestion_run",
        lambda **kwargs: IngestionRun(
            ingestion_run_id=7,
            started_at=now,
            finished_at=now,
            status="completed",
        ),
    )

    result = ingest_file(
        1,
        max_attempts=3,
    )

    assert writes["count"] == 2
    assert result.status == "completed"

def test_ingest_file_reuses_completed_ingestion(
    monkeypatch,
    tmp_path,
):
    source_file = SourceFile(
        file_id=1,
        filepath=tmp_path / "example.csv",
        timestamp_timezone="UTC",
        timestamp_format="%Y-%m-%d %H:%M:%S",
        reader_config={},
    )

    fingerprint = FileFingerprint(
        file_hash="sha256:test",
        file_size=100,
    )

    file_version = FileVersion(
        file_version_id=3,
        file_id=1,
        file_hash="sha256:test",
        file_size=100,
    )

    interface = SourceInterface(
        interface_id=4,
        file_id=1,
        deployment_id=10,
        values_column="value",
        timestamp_column="TIMESTAMP",
        unit="cm",
    )

    completed_run = IngestionRun(
        ingestion_run_id=7,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        status="completed",
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_source_file",
        lambda file_id: source_file,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.fingerprint_file",
        lambda path: fingerprint,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_or_create_file_version",
        lambda file_id, fingerprint: file_version,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_source_interfaces",
        lambda file_id: (interface,),
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_completed_ingestion_run",
        lambda file_version_id, interface_ids: completed_run,
    )

    def unexpected_create_run():
        raise AssertionError(
            "A new ingestion run must not be created"
        )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.create_ingestion_run_with_targets",
        unexpected_create_run,
    )

    result = ingest_file(1)

    assert result == completed_run

def test_ingest_file_rejects_partial_reingestion(
    monkeypatch,
    tmp_path,
):
    source_file = SourceFile(
        file_id=1,
        filepath=tmp_path / "example.csv",
        timestamp_timezone="UTC",
        timestamp_format="%Y-%m-%d %H:%M:%S",
        reader_config={},
    )

    interfaces = (
        SourceInterface(
            interface_id=1,
            file_id=1,
            deployment_id=10,
            values_column="temperature",
            timestamp_column="TIMESTAMP",
            unit="deg C",
        ),
        SourceInterface(
            interface_id=2,
            file_id=1,
            deployment_id=11,
            values_column="water_level",
            timestamp_column="TIMESTAMP",
            unit="cm",
        ),
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_source_file",
        lambda file_id: source_file,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.fingerprint_file",
        lambda path: FileFingerprint(
            file_hash="sha256:test",
            file_size=100,
        ),
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_or_create_file_version",
        lambda *args: FileVersion(
            file_version_id=3,
            file_id=1,
            file_hash="sha256:test",
            file_size=100,
        ),
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_source_interfaces",
        lambda file_id: interfaces,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_completed_ingestion_run",
        lambda *args: None,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_ingested_interface_ids",
        lambda file_version_id: {1},
    )

    with pytest.raises(
        ValueError,
        match="partially already ingested",
    ):
        ingest_file(1)

def test_create_ingestion_run_with_targets(monkeypatch):
    interface_1 = SourceInterface(
        interface_id=4,
        file_id=1,
        deployment_id=10,
        values_column="value_a",
        timestamp_column="TIMESTAMP",
        unit="cm",
    )

    interface_2 = SourceInterface(
        interface_id=5,
        file_id=1,
        deployment_id=11,
        values_column="value_b",
        timestamp_column="TIMESTAMP",
        unit="deg C",
    )

    now = datetime.now(timezone.utc)

    run_row = (
        7,
        now,
        None,
        "running",
    )

    class FakeCursor:
        def __init__(self):
            self.executed = None

        def executemany(self, query, values):
            self.executed = values

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class FakeResult:
        def fetchone(self):
            return run_row

    class FakeConnection:
        def __init__(self):
            self.cursor_instance = FakeCursor()

        def execute(self, query):
            return FakeResult()

        def cursor(self):
            return self.cursor_instance

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    connection = FakeConnection()

    monkeypatch.setattr(
        "dendroflow.ingestion.runs.connect",
        lambda database: connection,
    )

    run = create_ingestion_run_with_targets(
        3,
        (interface_1, interface_2),
    )

    assert run.ingestion_run_id == 7

    assert connection.cursor_instance.executed == [
        (7, 3, 4),
        (7, 3, 5),
    ]

def test_get_resumable_ingestion_run(monkeypatch):
    now = datetime.now(timezone.utc)

    class FakeResult:
        def fetchone(self):
            return (
                7,
                now,
                None,
                "running",
            )

    class FakeConnection:
        def execute(self, query, params):
            assert params == (
                2,
                3,
                [4, 5],
                2,
            )

            return FakeResult()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        "dendroflow.ingestion.runs.connect",
        lambda database: FakeConnection(),
    )

    run = get_resumable_ingestion_run(
        file_version_id=3,
        interface_ids=(5, 4),
    )

    assert run is not None
    assert run.ingestion_run_id == 7
    assert run.status == "running"

def test_get_resumable_ingestion_run_returns_none(
    monkeypatch,
):
    class FakeResult:
        def fetchone(self):
            return None

    class FakeConnection:
        def execute(self, query, params):
            return FakeResult()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        "dendroflow.ingestion.runs.connect",
        lambda database: FakeConnection(),
    )

    result = get_resumable_ingestion_run(
        file_version_id=3,
        interface_ids=(4, 5),
    )

    assert result is None

def test_get_ingestion_batch(monkeypatch):
    now = datetime.now(timezone.utc)

    row = (
        8,          # ingestion_batch_id
        7,          # ingestion_run_id
        3,          # file_version_id
        2,          # batch_number
        105,        # source_line_start
        204,        # source_line_end
        100,        # row_count
        "completed",
        1,          # attempt_count
        now,
        now,
        None,
    )

    class FakeResult:
        def fetchone(self):
            return row

    class FakeConnection:
        def execute(self, query, params):
            assert params == (
                7,
                3,
                2,
            )
            return FakeResult()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        "dendroflow.ingestion.batches.connect",
        lambda database: FakeConnection(),
    )

    batch = get_ingestion_batch(
        ingestion_run_id=7,
        file_version_id=3,
        batch_number=2,
    )

    assert batch is not None
    assert batch.ingestion_batch_id == 8
    assert batch.batch_number == 2
    assert batch.status == "completed"

def test_get_ingestion_batch_returns_none(
    monkeypatch,
):
    class FakeResult:
        def fetchone(self):
            return None

    class FakeConnection:
        def execute(self, query, params):
            return FakeResult()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        "dendroflow.ingestion.batches.connect",
        lambda database: FakeConnection(),
    )

    batch = get_ingestion_batch(
        ingestion_run_id=7,
        file_version_id=3,
        batch_number=2,
    )

    assert batch is None

def test_ingest_file_skips_completed_batch(
    monkeypatch,
    tmp_path,
):
    source_file = SourceFile(
        file_id=1,
        filepath=tmp_path / "example.csv",
        timestamp_timezone="UTC",
        timestamp_format="%Y-%m-%d %H:%M:%S",
        reader_config={},
    )

    interface = SourceInterface(
        interface_id=4,
        file_id=1,
        deployment_id=10,
        values_column="value",
        timestamp_column="TIMESTAMP",
        unit="cm",
    )

    now = datetime.now(timezone.utc)

    resumable_run = IngestionRun(
        ingestion_run_id=7,
        started_at=now,
        finished_at=None,
        status="running",
    )

    tabular_batch = TabularBatch(
        dataframe=pd.DataFrame(
            {
                "TIMESTAMP": ["2026-01-01 12:00:00"],
                "value": [10.5],
            }
        ),
        source_line_numbers=(5,),
    )

    completed_batch = IngestionBatch(
        ingestion_batch_id=8,
        ingestion_run_id=7,
        file_version_id=3,
        batch_number=1,
        source_line_start=5,
        source_line_end=5,
        row_count=1,
        status="completed",
        attempt_count=1,
        started_at=now,
        finished_at=now,
        error_message=None,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_source_file",
        lambda file_id: source_file,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.fingerprint_file",
        lambda path: FileFingerprint(
            file_hash="sha256:test",
            file_size=100,
        ),
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_or_create_file_version",
        lambda *args: FileVersion(
            file_version_id=3,
            file_id=1,
            file_hash="sha256:test",
            file_size=100,
        ),
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_source_interfaces",
        lambda file_id: (interface,),
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_completed_ingestion_run",
        lambda *args: None,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_ingested_interface_ids",
        lambda file_version_id: set(),
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_deployments",
        lambda ids: {},
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_resumable_ingestion_run",
        lambda *args: resumable_run,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.read_source_file",
        lambda file_id: iter((tabular_batch,)),
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_ingestion_batch",
        lambda ingestion_run_id, file_version_id, batch_number: completed_batch,
    )
 
    def unexpected_write(*args):
        raise AssertionError(
            "Completed batch must not be written again"
        )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.write_ingestion_batch",
        unexpected_write,
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.service.finalize_ingestion_run",
        lambda **kwargs: IngestionRun(
            ingestion_run_id=7,
            started_at=now,
            finished_at=now,
            status="completed",
        ),
    )

    result = ingest_file(1)

    assert result.status == "completed"
    assert result.ingestion_run_id == 7

def test_validate_ingestion_batch_checkpoint_rejects_mismatch():
    now = datetime.now(timezone.utc)

    ingestion_batch = IngestionBatch(
        ingestion_batch_id=8,
        ingestion_run_id=7,
        file_version_id=3,
        batch_number=1,
        source_line_start=5,
        source_line_end=104,
        row_count=100,
        status="completed",
        attempt_count=1,
        started_at=now,
        finished_at=now,
        error_message=None,
    )

    tabular_batch = TabularBatch(
        dataframe=pd.DataFrame({"value": [1, 2]}),
        source_line_numbers=(5, 6),
    )

    with pytest.raises(
        ValueError,
        match="checkpoint does not match",
    ):
        validate_ingestion_batch_checkpoint(
            ingestion_batch,
            tabular_batch,
        )
