from datetime import datetime, timezone

import pytest

from dendroflow.ingestion import (
    IngestionRun,
    SourceInterface,
    create_ingestion_run,
    create_ingestion_run_with_targets,
    finalize_ingestion_run,
    finish_ingestion_run,
    get_completed_ingestion_run,
    get_ingested_interface_ids,
    get_resumable_ingestion_run,
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
