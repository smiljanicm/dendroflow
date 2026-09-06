from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import pandas as pd

from dendroflow.tabular import TabularBatch

from dendroflow.ingestion import (
    Deployment,
    NormalizedObservation,
    SourceFile,
    SourceInterface,
    get_deployments,
    get_source_interfaces,
    normalize_batch,
    read_source_file,
)

def test_read_source_file_uses_registered_reader_config(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "example.csv"

    path.write_text(
        "skip this row\n"
        "timestamp,value\n"
        "2026-01-01 12:00:00,10.5\n"
        "2026-01-01 12:05:00,11.2\n"
    )

    source_file = SourceFile(
        file_id=1,
        filepath=path,
        timestamp_timezone="Europe/Berlin",
        timestamp_format="%Y-%m-%d %H:%M:%S",
        reader_config={
            "reader": "csv",
            "options": {
                "skiprows": [0],
            },
        },
    )

    monkeypatch.setattr(
        "dendroflow.ingestion.get_source_file",
        lambda file_id: source_file,
    )

    batches = list(read_source_file(1))

    assert len(batches) == 1


    batch = batches[0]
    dataframe = batch.dataframe

    assert list(dataframe.columns) == [
        "timestamp",
        "value",
    ]

    assert len(dataframe) == 2
    assert dataframe.iloc[0]["value"] == 10.5
    assert batch.source_line_numbers == (3, 4)

def test_get_source_interfaces(monkeypatch):
    class FakeResult:
        def fetchall(self):
            return [
                (
                    1,
                    7,
                    101,
                    "Lvl_cm_Avg",
                    "TIMESTAMP",
                    "cm",
                ),
                (
                    2,
                    7,
                    102,
                    "Temp_C_Avg",
                    "TIMESTAMP",
                    "deg C",
                ),
            ]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def execute(self, query, parameters):
            assert parameters == (7,)
            return FakeResult()

    monkeypatch.setattr(
        "dendroflow.ingestion.connect",
        lambda database: FakeConnection(),
    )

    interfaces = get_source_interfaces(7)

    assert len(interfaces) == 2

    assert interfaces[0] == SourceInterface(
        interface_id=1,
        file_id=7,
        deployment_id=101,
        values_column="Lvl_cm_Avg",
        timestamp_column="TIMESTAMP",
        unit="cm",
    )

    assert interfaces[1].values_column == "Temp_C_Avg"
    assert interfaces[1].deployment_id == 102

def test_get_deployments(monkeypatch):
    valid_from = datetime(
        2026, 1, 1,
        tzinfo=timezone.utc,
    )

    class FakeResult:
        def fetchall(self):
            return [
                (
                    101,
                    5,
                    10,
                    20,
                    valid_from,
                    None,
                ),
                (
                    102,
                    6,
                    11,
                    21,
                    valid_from,
                    None,
                ),
            ]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def execute(self, query, parameters):
            assert parameters == ([101, 102],)
            return FakeResult()

    monkeypatch.setattr(
        "dendroflow.ingestion.connect",
        lambda database: FakeConnection(),
    )

    deployments = get_deployments((101, 102))

    assert len(deployments) == 2

    assert deployments[101] == Deployment(
        deployment_id=101,
        sensor_id=5,
        location_id=10,
        variable_id=20,
        valid_from=valid_from,
        valid_to=None,
    )

    assert deployments[102].location_id == 11
    assert deployments[102].variable_id == 21

def test_normalize_batch():
    batch = TabularBatch(
        dataframe=pd.DataFrame(
            {
                "TIMESTAMP": [
                    "2026-01-01 12:00:00",
                    "2026-01-01 12:05:00",
                ],
                "temperature": [
                    10.5,
                    11.2,
                ],
                "water_level": [
                    3.1,
                    3.2,
                ],
            }
        ),
        source_line_numbers=(5, 6),
    )

    source_file = SourceFile(
        file_id=1,
        filepath=Path("example.csv"),
        timestamp_timezone="Europe/Berlin",
        timestamp_format="%Y-%m-%d %H:%M:%S",
        reader_config={},
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

    valid_from = datetime(
        2025,
        1,
        1,
        tzinfo=ZoneInfo("Europe/Berlin"),
    )

    deployments = {
        101: Deployment(
            deployment_id=101,
            sensor_id=1,
            location_id=10,
            variable_id=20,
            valid_from=valid_from,
            valid_to=None,
        ),
        102: Deployment(
            deployment_id=102,
            sensor_id=2,
            location_id=11,
            variable_id=21,
            valid_from=valid_from,
            valid_to=None,
        ),
    }

    observations = normalize_batch(
        batch,
        source_file,
        interfaces,
        deployments,
    )

    assert len(observations) == 4

    assert observations[0].location_id == 10
    assert observations[0].variable_id == 20
    assert observations[0].value == 10.5
    assert observations[0].interface_id == 1
    assert observations[0].source_row_number == 5

    assert observations[1].source_row_number == 6

    assert observations[2].location_id == 11
    assert observations[2].variable_id == 21
    assert observations[2].value == 3.1
    assert observations[2].source_row_number == 5

    assert observations[0].timestamp == datetime(
        2026,
        1,
        1,
        12,
        0,
        tzinfo=ZoneInfo("Europe/Berlin"),
    )
