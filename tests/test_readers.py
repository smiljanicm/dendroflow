from pathlib import Path

import pytest

from dendroflow.readers import CsvReader, reader_from_config


def test_csv_reader_reads_single_dataframe(tmp_path):
    path = tmp_path / "example.csv"

    path.write_text(
        "timestamp,temperature\n"
        "2026-01-01 12:00:00,10.5\n"
        "2026-01-01 12:05:00,11.2\n"
    )

    reader = CsvReader()

    batches = list(reader.read(path))

    assert len(batches) == 1

    dataframe = batches[0].dataframe

    assert list(dataframe.columns) == ["timestamp", "temperature"]
    assert len(dataframe) == 2
    assert dataframe.iloc[0]["temperature"] == 10.5
    assert batches[0].source_line_numbers == (2,3)

def test_csv_reader_reads_chunks(tmp_path):
    path = tmp_path / "example.csv"

    path.write_text(
        "value\n"
        "1\n"
        "2\n"
        "3\n"
        "4\n"
        "5\n"
    )

    reader = CsvReader(chunksize=2)

    batches = list(reader.read(path))

    assert len(batches) == 3
    assert [len(batch.dataframe) for batch in batches] == [2, 2, 1]

    assert batches[0].source_line_numbers == (2, 3)
    assert batches[1].source_line_numbers == (4, 5)
    assert batches[2].source_line_numbers == (6,)

DATA_DIR = Path(__file__).parent / "data"

def test_csv_reader_reads_toa5_data():
    path = DATA_DIR / "Sandhagen_Rewetted_WaterTbl.dat"

    reader = CsvReader(
        skiprows=[0,2,3],
    )

    batches = list(reader.read(path))

    dataframe = batches[0].dataframe

    assert len(batches) == 1

    assert list(dataframe.columns) == [
        "TIMESTAMP",
        "RECORD",
        "Lvl_cm_Avg",
        "Temp_C_Avg",
    ]

    assert len(dataframe) > 0

def test_reader_from_config():
    config = {
        "reader": "csv",
        "options": {
            "skiprows": [0, 2, 3],
        },
    }

    reader = reader_from_config(config)

    assert isinstance(reader, CsvReader)
    assert reader.skiprows == [0, 2, 3]

def test_reader_from_config_rejects_unknown_reader():
    config = {
        "reader": "unknown",
        "options": {},
    }

    with pytest.raises(ValueError, match="Unsupported reader type"):
        reader_from_config(config)

def test_csv_reader_reads_toa5_source_line_numbers():
    path = DATA_DIR / "Sandhagen_Rewetted_WaterTbl.dat"

    reader = CsvReader(
        skiprows=[0, 2, 3],
    )

    batches = list(reader.read(path))

    assert len(batches) == 1

    batch = batches[0]
    dataframe = batch.dataframe

    assert list(dataframe.columns) == [
        "TIMESTAMP",
        "RECORD",
        "Lvl_cm_Avg",
        "Temp_C_Avg",
    ]

    assert len(dataframe) > 0

    assert batch.source_line_numbers[0] == 5
    assert batch.source_line_numbers[1] == 6

def test_csv_reader_integer_skiprows_preserves_physical_lines(
    tmp_path,
):
    path = tmp_path / "example.csv"

    path.write_text(
        "metadata\n"
        "TIMESTAMP,value\n"
        "2026-01-01 00:00:00,1\n"
        "2026-01-01 00:15:00,2\n"
    )

    reader = CsvReader(
        skiprows=1,
        header=0,
    )

    batch = next(reader.read(path))

    assert batch.source_line_numbers == (3, 4)
