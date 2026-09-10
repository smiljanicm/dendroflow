from dendroflow.configuration import metadata


class FakeResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


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


def test_find_site_returns_existing_row(monkeypatch):
    connection = FakeConnection(
        (
            7,
            "sandhagen_rewetted",
            "Sandhagen Rewetted",
            None,
            54.0,
            13.0,
            None,
        )
    )

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    result = metadata.find_site("sandhagen_rewetted")

    assert result is not None
    assert result.database_id == 7
    assert result.values["site_code"] == "sandhagen_rewetted"
    assert result.values["name"] == "Sandhagen Rewetted"
    assert connection.parameters == ("sandhagen_rewetted",)


def test_find_site_returns_none_when_missing(monkeypatch):
    connection = FakeConnection(None)

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    assert metadata.find_site("missing") is None


def test_find_location_type_uses_type_column(monkeypatch):
    connection = FakeConnection(
        (
            3,
            "well",
            "Water-table monitoring location",
        )
    )

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    result = metadata.find_location_type("well")

    assert result is not None
    assert result.database_id == 3
    assert result.values["type"] == "well"
    assert "WHERE type = %s" in connection.query


def test_find_variable_returns_full_existing_state(monkeypatch):
    connection = FakeConnection(
        (
            1,
            "water_level",
            False,
            "Water level",
        )
    )

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    result = metadata.find_variable("water_level")

    assert result is not None
    assert result.database_id == 1
    assert result.values == {
        "variable": "water_level",
        "derived": False,
        "description": "Water level",
    }


