"""Read-only PostgreSQL verification; no fixture rows are inserted or deleted."""

import os
from contextlib import contextmanager

import pandas as pd
import pytest

from dendroflow.configuration.workbook import source
from dendroflow.configuration.workbook.schema import RESOURCE_SHEETS
from dendroflow.database import connect

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("DENDROFLOW_INTEGRATION") != "1",
        reason="Set DENDROFLOW_INTEGRATION=1 to run PostgreSQL integration tests",
    ),
]


def test_read_configuration_frames_uses_read_only_repeatable_read(monkeypatch):
    modes = {}
    connections = []

    class ObservedConnection:
        def __init__(self, database, connection):
            self.database = database
            self.connection = connection

        def execute(self, query):
            cursor = self.connection.execute(query)
            if isinstance(query, str) and query.startswith("SET TRANSACTION"):
                with self.connection.execute(
                    "SELECT current_setting('transaction_read_only'), "
                    "current_setting('transaction_isolation')"
                ) as settings:
                    modes[self.database] = settings.fetchone()
            return cursor

    @contextmanager
    def observe(database):
        with connect(database) as connection:
            connections.append(connection)
            yield ObservedConnection(database, connection)

    monkeypatch.setattr(source, "connect", observe)
    frames = source.read_configuration_frames()

    assert modes == {
        "dendroflow_metadata": ("on", "repeatable read"),
        "dendroflow_raw": ("on", "repeatable read"),
    }
    assert len(connections) == 2
    assert all(connection.closed for connection in connections)
    assert tuple(frames) == tuple(sheet.name for sheet in RESOURCE_SHEETS)
    for spec in RESOURCE_SHEETS:
        frame = frames[spec.name]
        assert isinstance(frame, pd.DataFrame)
        assert frame.columns[0] == spec.id_column
        assert all(dtype == object for dtype in frame.dtypes)
        assert frame[spec.id_column].is_unique
        assert frame[spec.id_column].is_monotonic_increasing
