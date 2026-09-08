from collections.abc import Iterator
from pathlib import Path

from dendroflow.database import connect
from dendroflow.readers import reader_from_config
from dendroflow.tabular import TabularBatch

from .models import (
    Deployment,
    SourceFile,
    SourceInterface,
)


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


def read_source_file(file_id: int) -> Iterator[TabularBatch]:
    """Read a registered source file using its database configuration."""

    source_file = get_source_file(file_id)

    reader = reader_from_config(
        source_file.reader_config
    )

    yield from reader.read(
        source_file.filepath
    )


def get_source_interfaces(
    file_id: int,
) -> tuple[SourceInterface, ...]:
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


def get_deployments(
    deployment_ids: tuple[int, ...],
) -> dict[int, Deployment]:
    """Load deployments needed for ingestion."""

    if not deployment_ids:
        return {}

    with connect("dendroflow_metadata") as connection:
        rows = connection.execute(
            """
            SELECT
                deployment_id,
                sensor_id,
                location_id,
                variable_id,
                valid_from,
                valid_to
            FROM deployments
            WHERE deployment_id = ANY(%s)
            """,
            (list(deployment_ids),),
        ).fetchall()

    return {
        row[0]: Deployment(
            deployment_id=row[0],
            sensor_id=row[1],
            location_id=row[2],
            variable_id=row[3],
            valid_from=row[4],
            valid_to=row[5],
        )
        for row in rows
    }
