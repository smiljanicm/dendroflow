import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from dendroflow.configuration.workbook import source
from dendroflow.configuration.workbook.schema import RESOURCE_SHEETS

METADATA = "dendroflow_metadata"
RAW = "dendroflow_raw"
SET_TRANSACTION = "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def fetchall(self):
        return deepcopy(self.rows)


class FakeConnection:
    def __init__(self, database, records, failure):
        self.database = database
        self.records = records
        self.failure = failure
        self.statements = []
        self.cursors = []
        self.closed = False
        self.exit_error = None

    def __enter__(self):
        return self

    def __exit__(self, error_type, error, traceback):
        self.closed = True
        self.exit_error = error
        if self.failure == (self.database, "exit"):
            raise RuntimeError("exit failed")

    def execute(self, query):
        text = query if isinstance(query, str) else query.as_string()
        self.statements.append(text)
        if text == SET_TRANSACTION:
            if self.failure == (self.database, "setup"):
                raise RuntimeError("setup failed")
            return FakeCursor([])
        assert self.statements[0] == SET_TRANSACTION
        match = re.fullmatch(r'SELECT (.+) FROM "(\w+)" ORDER BY "(\w+)"', text)
        assert match is not None, text
        columns = re.findall(r'"(\w+)"', match[1])
        table, primary_key = match[2], match[3]
        assert primary_key == columns[0]
        if self.failure == (self.database, table):
            raise RuntimeError("query failed")
        records = self.records.get((self.database, table), [])
        rows = [
            tuple(record[column] for column in columns)
            for record in sorted(records, key=lambda record: record[primary_key])
        ]
        cursor = FakeCursor(rows)
        self.cursors.append(cursor)
        return cursor


@pytest.fixture
def database(monkeypatch):
    records = {}
    connections = []
    attempts = []
    failure = [None]

    def connect(name):
        attempts.append(name)
        if failure[0] == (name, "connect"):
            raise RuntimeError("connect failed")
        connection = FakeConnection(name, records, failure[0])
        connections.append(connection)
        return connection

    monkeypatch.setattr(source, "connect", connect)
    return records, connections, attempts, failure


def site(database_id, parent_id=None):
    return {
        "site_id": database_id, "site_code": "0012", "name": "Site",
        "description": None, "latitude": 0.0, "longitude": 12.5,
        "parent_id": parent_id,
    }


def test_empty_databases_return_all_frames_with_primary_keys(database):
    frames = source.read_configuration_frames()
    assert tuple(frames) == tuple(sheet.name for sheet in RESOURCE_SHEETS)
    for sheet in RESOURCE_SHEETS:
        frame = frames[sheet.name]
        assert isinstance(frame, pd.DataFrame)
        assert frame.empty
        assert frame.columns[0] == sheet.id_column
        assert all(dtype == object for dtype in frame.dtypes)


def test_each_database_has_one_owned_read_only_transaction(database):
    _, connections, attempts, _ = database
    source.read_configuration_frames()
    assert attempts == [METADATA, RAW]
    assert [len(connection.statements) for connection in connections] == [10, 3]
    for connection in connections:
        assert connection.statements[0] == SET_TRANSACTION
        assert connection.closed
        assert connection.exit_error is None
        assert all(cursor.closed for cursor in connection.cursors)


def test_queries_read_only_configuration_tables_without_joins_or_filters(database):
    _, connections, _, _ = database
    source.read_configuration_frames()
    actual = {
        connection.database: [
            re.search(r'FROM "(\w+)"', statement)[1]
            for statement in connection.statements[1:]
        ]
        for connection in connections
    }
    assert actual == {
        METADATA: [
            "sites", "location_types", "sensor_types", "variables",
            "sensor_models", "sensors", "locations", "location_labels", "deployments",
        ],
        RAW: ["files", "sensor_file_interfaces"],
    }
    for connection in connections:
        for statement in connection.statements[1:]:
            assert statement.startswith("SELECT ")
            assert "*" not in statement
            assert "WHERE" not in statement
            assert "JOIN" not in statement


def test_large_and_nullable_ids_do_not_become_floats(database):
    records, *_ = database
    largest = 2**63 - 1
    records[METADATA, "sites"] = [site(largest, largest - 1), site(1)]
    frame = source.read_configuration_frames()["sites"]
    assert frame["site_id"].tolist() == [1, largest]
    assert type(frame.at[1, "site_id"]) is int
    assert frame.at[0, "parent_id"] is None
    assert frame.at[1, "parent_id"] == largest - 1
    assert type(frame.at[1, "parent_id"]) is int
    assert frame.at[0, "site_code"] == "0012"
    assert frame.at[0, "latitude"] == 0.0
    assert frame.at[0, "description"] is None


def test_booleans_nulls_and_literal_text_are_preserved(database):
    records, *_ = database
    records[METADATA, "variables"] = [{
        "variable_id": 1, "variable": "NA", "derived": False, "description": None,
    }]
    frame = source.read_configuration_frames()["variables"]
    assert frame.at[0, "derived"] is False
    assert frame.at[0, "variable"] == "NA"
    assert frame.at[0, "description"] is None


def test_timestamps_remain_timezone_aware_python_values(database):
    records, *_ = database
    when = datetime(2026, 1, 1, 12, 30, 5, 123456, tzinfo=timezone(timedelta(hours=2)))
    records[METADATA, "deployments"] = [{
        "deployment_id": 9, "sensor_id": 2, "location_id": 3, "variable_id": 4,
        "valid_from": when, "valid_to": None,
    }]
    frame = source.read_configuration_frames()["deployments"]
    assert type(frame.at[0, "valid_from"]) is datetime
    assert frame.at[0, "valid_from"] == when
    assert frame.at[0, "valid_from"].utcoffset() == timedelta(hours=2)
    assert frame.at[0, "valid_to"] is None


def test_raw_data_retains_json_and_database_column_names(database):
    records, *_ = database
    reader = {"reader": "csv", "options": {"skiprows": [0, 2], "na_values": ["NAN"]}}
    records[RAW, "files"] = [{
        "file_id": 8, "filepath": "/does-not-exist/source.dat",
        "timestamp_timezone": "UTC", "timestamp_format": "%Y-%m-%d",
        "reader_config": reader,
    }]
    records[RAW, "sensor_file_interfaces"] = [{
        "interface_id": 4, "file_id": 8, "deployment_id": 100,
        "timestamp_column": "TIMESTAMP", "values_column": "value", "unit": None,
    }]
    frames = source.read_configuration_frames()
    assert frames["files"].at[0, "reader_config"] == reader
    assert frames["files"].at[0, "filepath"] == "/does-not-exist/source.dat"
    assert frames["interfaces"].at[0, "deployment_id"] == 100
    assert frames["interfaces"].at[0, "unit"] is None
    assert "path" not in frames["files"].columns
    assert "row_role" not in frames["interfaces"].columns


def test_reader_does_not_drop_unlabelled_locations_or_legacy_values(database):
    records, *_ = database
    records[METADATA, "locations"] = [{
        "location_id": 7, "site_id": 1, "location_type_id": 2,
        "latitude": None, "longitude": None, "height_above_ground": None, "azimuth": None,
    }]
    records[METADATA, "sensor_models"] = [{
        "sensor_model_id": 3, "manufacturer": None, "model": "Old", "sensor_type_id": 2,
    }]
    frames = source.read_configuration_frames()
    assert frames["locations"]["location_id"].tolist() == [7]
    assert frames["location_labels"].empty
    assert frames["sensor_models"].at[0, "manufacturer"] is None


def test_each_call_reads_fresh_data_and_returns_independent_frames(database):
    records, _, attempts, _ = database
    records[METADATA, "sites"] = [site(1)]
    first = source.read_configuration_frames()
    first["sites"].at[0, "name"] = "Caller edit"
    records[METADATA, "sites"][0]["name"] = "Changed in database"
    second = source.read_configuration_frames()
    assert second["sites"].at[0, "name"] == "Changed in database"
    assert first["sites"].at[0, "name"] == "Caller edit"
    assert attempts == [METADATA, RAW, METADATA, RAW]


@pytest.mark.parametrize(("database_name", "stage"), [
    (METADATA, "connect"), (METADATA, "setup"), (METADATA, "sensors"),
    (METADATA, "exit"), (RAW, "connect"), (RAW, "setup"),
    (RAW, "sensor_file_interfaces"), (RAW, "exit"),
])
def test_errors_propagate_without_returning_partial_frames(database, database_name, stage):
    _, connections, attempts, failure = database
    failure[0] = (database_name, stage)
    with pytest.raises(RuntimeError, match="failed"):
        source.read_configuration_frames()
    assert attempts == ([METADATA] if database_name == METADATA else [METADATA, RAW])
    assert all(connection.closed for connection in connections)
    if stage in {"setup", "sensors", "sensor_file_interfaces"}:
        assert isinstance(connections[-1].exit_error, RuntimeError)


def test_dataframe_conversion_error_closes_connection_and_stops(database, monkeypatch):
    _, connections, attempts, _ = database

    def fail_conversion(*args, **kwargs):
        raise ValueError("conversion failed")

    monkeypatch.setattr(source.pd, "DataFrame", fail_conversion)
    with pytest.raises(ValueError, match="conversion failed"):
        source.read_configuration_frames()
    assert attempts == [METADATA]
    assert connections[0].closed
    assert isinstance(connections[0].exit_error, ValueError)
