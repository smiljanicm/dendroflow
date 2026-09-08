from datetime import datetime, timezone

import pandas as pd
import pytest

from dendroflow.ingestion import (
    IngestionBatch,
    complete_ingestion_batch,
    create_ingestion_batch,
    fail_ingestion_batch,
    get_ingestion_batch,
    start_ingestion_batch,
    validate_ingestion_batch_checkpoint,
)
from dendroflow.tabular import TabularBatch

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
