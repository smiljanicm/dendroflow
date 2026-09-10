import pytest

from dendroflow.configuration import metadata


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


def test_find_sensor_models_by_manufacturer_and_model(monkeypatch):
    connection = FakeConnection(
        [
            (
                3,
                "CS451",
                "Campbell Scientific",
                1,
            )
        ]
    )

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    result = metadata.find_sensor_models(
        manufacturer="Campbell Scientific",
        model="CS451",
    )

    assert len(result) == 1
    assert result[0].database_id == 3
    assert result[0].values == {
        "model": "CS451",
        "manufacturer": "Campbell Scientific",
        "sensor_type_id": 1,
    }
    assert connection.parameters == (
        "Campbell Scientific",
        "CS451",
    )
    assert "ORDER BY sensor_model_id" in connection.query


def test_find_sensor_models_by_model_can_return_multiple(
    monkeypatch,
):
    connection = FakeConnection(
        [
            (3, "CS451", "Campbell Scientific", 1),
            (8, "CS451", "Other Manufacturer", 2),
        ]
    )

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    result = metadata.find_sensor_models(
        model="CS451"
    )

    assert len(result) == 2
    assert connection.parameters == ("CS451",)


def test_find_sensor_models_by_manufacturer(monkeypatch):
    connection = FakeConnection(
        [
            (3, "CS451", "Campbell Scientific", 1),
            (4, "CR1000", "Campbell Scientific", 2),
        ]
    )

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    result = metadata.find_sensor_models(
        manufacturer="Campbell Scientific"
    )

    assert len(result) == 2
    assert connection.parameters == (
        "Campbell Scientific",
    )


def test_find_sensor_models_requires_selector():
    with pytest.raises(
        ValueError,
        match="requires manufacturer or model",
    ):
        metadata.find_sensor_models()


