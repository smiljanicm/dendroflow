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


def test_find_sensors_by_exact_identity(monkeypatch):
    connection = FakeConnection(
        [
            (
                7,
                3,
                "123456",
                "Water level sensor",
            )
        ]
    )

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    result = metadata.find_sensors(
        serial_number="123456",
        sensor_model_id=3,
    )

    assert len(result) == 1
    assert result[0].database_id == 7
    assert result[0].values == {
        "sensor_model_id": 3,
        "serial_number": "123456",
        "description": "Water level sensor",
    }
    assert connection.parameters == ("123456", 3)


def test_find_sensors_by_serial_can_return_multiple(monkeypatch):
    connection = FakeConnection(
        [
            (7, 3, "123456", None),
            (8, 4, "123456", None),
        ]
    )

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    result = metadata.find_sensors(
        serial_number="123456"
    )

    assert len(result) == 2
    assert connection.parameters == ("123456",)


def test_find_sensors_by_sensor_model(monkeypatch):
    connection = FakeConnection(
        [
            (7, 3, "123456", None),
            (9, 3, "987654", None),
        ]
    )

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    result = metadata.find_sensors(
        sensor_model_id=3
    )

    assert len(result) == 2
    assert connection.parameters == (3,)


def test_find_sensors_requires_selector():
    with pytest.raises(
        ValueError,
        match="requires serial_number or sensor_model_id",
    ):
        metadata.find_sensors()


def test_find_locations_by_site_and_initial_label(monkeypatch):
    connection = FakeConnection(
        [
            (
                3,
                1,
                2,
                54.0,
                13.0,
                0.0,
                None,
                "Rewetted well",
                "2025-04-01T00:00:00+00:00",
                None,
            )
        ]
    )

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    result = metadata.find_locations(
        site_id=1,
        initial_label="Rewetted well",
    )

    assert len(result) == 1
    assert result[0].database_id == 3
    assert result[0].values["site_id"] == 1
    assert result[0].values["initial_label"] == "Rewetted well"
    assert connection.parameters == (
        1,
        "Rewetted well",
    )
    assert "ORDER BY" in connection.query
    assert "location_labels.valid_from" in connection.query


def test_find_locations_by_site_can_return_multiple(monkeypatch):
    connection = FakeConnection(
        [
            (
                3, 1, 2, None, None, None, None,
                "Well A", "2025-01-01T00:00:00+00:00", None,
            ),
            (
                4, 1, 2, None, None, None, None,
                "Well B", "2025-01-01T00:00:00+00:00", None,
            ),
        ]
    )

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    result = metadata.find_locations(site_id=1)

    assert len(result) == 2
    assert connection.parameters == (1,)


def test_find_locations_by_initial_label_can_return_multiple(
    monkeypatch,
):
    connection = FakeConnection(
        [
            (
                3, 1, 2, None, None, None, None,
                "Well 01", "2025-01-01T00:00:00+00:00", None,
            ),
            (
                9, 4, 2, None, None, None, None,
                "Well 01", "2025-01-01T00:00:00+00:00", None,
            ),
        ]
    )

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    result = metadata.find_locations(
        initial_label="Well 01"
    )

    assert len(result) == 2
    assert connection.parameters == ("Well 01",)


def test_find_locations_requires_selector():
    with pytest.raises(
        ValueError,
        match="requires site_id or initial_label",
    ):
        metadata.find_locations()


def test_find_location_labels_returns_ordered_history(
    monkeypatch,
):
    connection = FakeConnection(
        [
            (
                10,
                3,
                "Well A",
                "2025-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
            (
                11,
                3,
                "Well B",
                "2026-01-01T00:00:00+00:00",
                None,
            ),
        ]
    )

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    result = metadata.find_location_labels(3)

    assert len(result) == 2

    assert result[0].database_id == 10
    assert result[0].values["location_id"] == 3
    assert result[0].values["label"] == "Well A"

    assert result[1].database_id == 11
    assert result[1].values["label"] == "Well B"

    assert connection.parameters == (3,)
    assert "ORDER BY" in connection.query
    assert "valid_from" in connection.query
    assert "location_label_id" in connection.query


def test_find_location_labels_returns_empty_history(
    monkeypatch,
):
    connection = FakeConnection([])

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    result = metadata.find_location_labels(3)

    assert result == ()


def test_find_location_labels_requires_positive_location_id():
    with pytest.raises(
        ValueError,
        match="location_id must be greater than zero",
    ):
        metadata.find_location_labels(0)


def test_find_deployments_by_exact_identity(monkeypatch):
    valid_from = "2025-04-01T00:00:00+00:00"

    connection = FakeConnection(
        [
            (
                12,
                5,
                3,
                7,
                valid_from,
                None,
            )
        ]
    )

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    result = metadata.find_deployments(
        sensor_id=5,
        location_id=3,
        variable_id=7,
        valid_from=valid_from,
    )

    assert len(result) == 1
    assert result[0].database_id == 12
    assert result[0].values == {
        "sensor_id": 5,
        "location_id": 3,
        "variable_id": 7,
        "valid_from": valid_from,
        "valid_to": None,
    }

    assert connection.parameters == (
        5,
        3,
        7,
        valid_from,
    )
    assert "ORDER BY deployment_id" in connection.query


def test_find_deployments_by_sensor_and_variable_can_return_history(
    monkeypatch,
):
    connection = FakeConnection(
        [
            (
                12,
                5,
                3,
                7,
                "2025-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
            (
                13,
                5,
                4,
                7,
                "2026-01-01T00:00:00+00:00",
                None,
            ),
        ]
    )

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    result = metadata.find_deployments(
        sensor_id=5,
        variable_id=7,
    )

    assert len(result) == 2
    assert connection.parameters == (5, 7)


def test_find_deployments_with_partial_selector_can_return_multiple(
    monkeypatch,
):
    connection = FakeConnection(
        [
            (
                12,
                5,
                3,
                7,
                "2025-01-01T00:00:00+00:00",
                None,
            ),
            (
                14,
                8,
                3,
                9,
                "2025-06-01T00:00:00+00:00",
                None,
            ),
        ]
    )

    monkeypatch.setattr(
        metadata,
        "connect",
        lambda database: connection,
    )

    result = metadata.find_deployments(
        location_id=3,
    )

    assert len(result) == 2
    assert connection.parameters == (3,)


def test_find_deployments_requires_selector():
    with pytest.raises(
        ValueError,
        match="requires at least one identifying field",
    ):
        metadata.find_deployments()

