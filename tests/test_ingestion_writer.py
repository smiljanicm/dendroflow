from datetime import datetime, timezone

import pytest

from dendroflow.ingestion import (
    IngestionBatch,
    NormalizedObservation,
    write_ingestion_batch,
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
