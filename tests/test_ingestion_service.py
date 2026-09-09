from datetime import datetime, timezone

import pandas as pd
import pytest

from dendroflow.ingestion import (
    Deployment,
    FileFingerprint,
    FileVersion,
    IngestionBatch,
    IngestionRun,
    NormalizedObservation,
    SourceFile,
    SourceInterface,
    ingest_file,
    insert_raw_observations,
)
from dendroflow.tabular import TabularBatch


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
