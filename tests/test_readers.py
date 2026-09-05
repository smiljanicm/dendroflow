from pathlib import Path

from dendroflow.readers import CsvReader

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

    dataframe = batches[0]

    assert list(dataframe.columns) == ["timestamp", "temperature"]
    assert len(dataframe) == 2
    assert dataframe.iloc[0]["temperature"] == 10.5

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
    assert [len(batch) for batch in batches] == [2, 2, 1]

DATA_DIR = Path(__file__).parent / "data"

def test_csv_reader_reads_toa5_data():
    path = DATA_DIR / "Sandhagen_Rewetted_WaterTbl.dat"

    reader = CsvReader(
        skiprows=[0,2,3],
    )

    batches = list(reader.read(path))

    dataframe = batches[0]

    assert len(batches) == 1

    assert list(dataframe.columns) == [
        "TIMESTAMP",
        "RECORD",
        "Lvl_cm_Avg",
        "Temp_C_Avg",
    ]

    assert len(dataframe) > 0
