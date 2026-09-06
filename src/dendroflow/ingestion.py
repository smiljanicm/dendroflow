from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from dendroflow.database import connect
from dendroflow.readers import reader_from_config


@dataclass(frozen=True)
class SourceFile:
    """Represent a source file registered in DendroFlow."""

    file_id: int
    filepath: Path
    timestamp_timezone: str
    timestamp_format: str
    reader_config: dict[str, Any]

def get_source_file(file_id: int) -> SourceFile:
    """Load a source-file definition from the RAW database."""

    with connect("dendroflow_raw") as connection:
        row = connection.execute(
            """
            SELECT
                file_id,
                filepath,
                timestamp_timezone,
                timestamp_format,
                reader_config
            FROM files
            WHERE file_id = %s
            """,
            (file_id,),
        ).fetchone()

    if row is None:
        raise ValueError(f"Unknown file_id: {file_id}")

    return SourceFile(
        file_id=row[0],
        filepath=Path(row[1]),
        timestamp_timezone=row[2],
        timestamp_format=row[3],
        reader_config=row[4],
    )


def read_source_file(file_id: int) -> Iterator[pd.DataFrame]:
    """Read a registered source file using its database configuration."""

    source_file = get_source_file(file_id)

    reader = reader_from_config(source_file.reader_config)

    yield from reader.read(source_file.filepath)

@dataclass(frozen=True)
class SourceInterface:
    """Represent one measurement interface registered for a source file."""

    interface_id: int
    file_id: int
    deployment_id: int
    values_column: str
    timestamp_column: str
    unit: str | None


def get_source_interfaces(file_id: int) -> tuple[SourceInterface, ...]:
    """Load measurement interfaces registered for a source file."""

    with connect("dendroflow_raw") as connection:
        rows = connection.execute(
            """
            SELECT
                interface_id,
                file_id,
                deployment_id,
                values_column,
                timestamp_column,
                unit
            FROM sensor_file_interfaces
            WHERE file_id = %s
            ORDER BY interface_id
            """,
            (file_id,),
        ).fetchall()

    return tuple(
        SourceInterface(
            interface_id=row[0],
            file_id=row[1],
            deployment_id=row[2],
            values_column=row[3],
            timestamp_column=row[4],
            unit=row[5],
        )
        for row in rows
    )
