import pytest

from dendroflow.configuration import raw


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        if self.rows is None:
            return None

        if isinstance(self.rows, list):
            return self.rows[0] if self.rows else None

        return self.rows

    def fetchall(self):
        if self.rows is None:
            return []

        if isinstance(self.rows, list):
            return self.rows

        return [self.rows]


class FakeConnection:
    def __init__(self, row):
        self.row = row
        self.query = None
        self.parameters = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def execute(self, query, parameters):
        self.query = query
        self.parameters = parameters
        return FakeResult(self.row)


def test_find_file_returns_existing_file(monkeypatch):
    connection = FakeConnection(
        [
            (
                3,
                "tests/data/Sandhagen_Rewetted_WaterTbl.dat",
                "Etc/GMT-1",
                "%Y-%m-%d %H:%M:%S",
                {
                    "reader": "csv",
                    "options": {
                        "delimiter": ",",
                    },
                },
            )
        ]
    )

    monkeypatch.setattr(
        raw,
        "connect",
        lambda database: connection,
    )

    result = raw.find_file(
        "tests/data/Sandhagen_Rewetted_WaterTbl.dat"
    )

    assert result is not None
    assert result.database_id == 3
    assert result.values == {
        "filepath": (
            "tests/data/Sandhagen_Rewetted_WaterTbl.dat"
        ),
        "timestamp_timezone": "Etc/GMT-1",
        "timestamp_format": "%Y-%m-%d %H:%M:%S",
        "reader_config": {
            "reader": "csv",
            "options": {
                "delimiter": ",",
            },
        },
    }

    assert connection.parameters == (
        "tests/data/Sandhagen_Rewetted_WaterTbl.dat",
    )


def test_find_file_returns_none_when_missing(monkeypatch):
    connection = FakeConnection([])

    monkeypatch.setattr(
        raw,
        "connect",
        lambda database: connection,
    )

    result = raw.find_file("missing.dat")

    assert result is None


def test_find_file_interfaces_returns_interfaces(monkeypatch):
    connection = FakeConnection(
        [
            (
                10,
                3,
                21,
                "Lvl_cm_Avg",
                "TIMESTAMP",
                "cm",
            ),
            (
                11,
                3,
                22,
                "Temp_C_Avg",
                "TIMESTAMP",
                "deg C",
            ),
        ]
    )

    monkeypatch.setattr(
        raw,
        "connect",
        lambda database: connection,
    )

    result = raw.find_file_interfaces(3)

    assert len(result) == 2

    assert result[0].database_id == 10
    assert result[0].values == {
        "file_id": 3,
        "deployment_id": 21,
        "values_column": "Lvl_cm_Avg",
        "timestamp_column": "TIMESTAMP",
        "unit": "cm",
    }

    assert result[1].database_id == 11
    assert result[1].values["values_column"] == "Temp_C_Avg"

    assert connection.parameters == (3,)
    assert "ORDER BY interface_id" in connection.query


def test_find_file_interfaces_returns_empty_tuple(
    monkeypatch,
):
    connection = FakeConnection([])

    monkeypatch.setattr(
        raw,
        "connect",
        lambda database: connection,
    )

    result = raw.find_file_interfaces(3)

    assert result == ()


def test_find_file_interfaces_requires_positive_file_id():
    with pytest.raises(
        ValueError,
        match="file_id must be greater than zero",
    ):
        raw.find_file_interfaces(0)


