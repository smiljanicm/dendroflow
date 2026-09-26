import pytest

from dendroflow.ingestion.locks import (
    FileIngestionInProgressError,
    file_ingestion_lock,
)


class FakeConnection:
    def __init__(self, acquired):
        self.acquired = acquired
        self.commits = 0
        self.closed = False

    def execute(self, query, parameters):
        assert "pg_try_advisory_lock" in query
        assert parameters == ("dendroflow:raw-ingestion:file:17",)
        return self

    def fetchone(self):
        return (self.acquired,)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def test_file_lock_holds_connection_until_context_exits(monkeypatch):
    connection = FakeConnection(acquired=True)
    monkeypatch.setattr(
        "dendroflow.ingestion.locks.connect",
        lambda database: connection,
    )

    with file_ingestion_lock(17):
        assert not connection.closed
        assert connection.commits == 1

    assert connection.closed


def test_file_lock_rejects_an_existing_worker_and_closes_connection(
    monkeypatch,
):
    connection = FakeConnection(acquired=False)
    monkeypatch.setattr(
        "dendroflow.ingestion.locks.connect",
        lambda database: connection,
    )

    with pytest.raises(FileIngestionInProgressError, match="already running"), file_ingestion_lock(17):
        pytest.fail("lock context should not be entered")

    assert connection.closed
