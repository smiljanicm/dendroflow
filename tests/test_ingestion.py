from datetime import datetime, timezone

from dendroflow.ingestion import (
    Deployment,
    SourceFile,
    SourceInterface,
    get_deployments,
    get_source_interfaces,
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
