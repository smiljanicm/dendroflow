from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from dendroflow.ingestion import (
    Deployment,
    SourceFile,
    SourceInterface,
    normalize_batch,
)
from dendroflow.tabular import TabularBatch


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

