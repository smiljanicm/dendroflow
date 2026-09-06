from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from hashlib import sha256

import pandas as pd

from dendroflow.database import connect
from dendroflow.readers import reader_from_config
from dendroflow.tabular import TabularBatch

from datetime import datetime

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


def read_source_file(file_id: int) -> Iterator[TabularBatch]:
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

@dataclass(frozen=True)
class Deployment:
    """Represent deployment metadata needed during ingestion."""

    deployment_id: int
    sensor_id: int
    location_id: int
    variable_id: int
    valid_from: datetime
    valid_to: datetime


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

@dataclass(frozen=True)
class NormalizedObservation:
    """Represent one observation ready for RAW ingestion."""

    location_id: int
    variable_id: int
    timestamp: datetime
    value: float
    interface_id: int
    source_row_number: int

def normalize_batch(
    batch: TabularBatch,
    source_file: SourceFile,
    interfaces: tuple[SourceInterface, ...],
    deployments: dict[int, Deployment],
) -> tuple[NormalizedObservation, ...]:
    """Convert one tabular batch into normalized RAW observations."""

    dataframe = batch.dataframe
    observations: list[NormalizedObservation] = []

    for interface in interfaces:
        if interface.values_column not in dataframe.columns:
            raise ValueError(
                f"Missing values column: {interface.values_column}"
            )

        if interface.timestamp_column not in dataframe.columns:
            raise ValueError(
                f"Missing timestamp column: {interface.timestamp_column}"
            )

        deployment = deployments.get(interface.deployment_id)

        if deployment is None:
            raise ValueError(
                f"Missing deployment: {interface.deployment_id}"
            )

        timestamps = pd.to_datetime(
            dataframe[interface.timestamp_column],
            format=source_file.timestamp_format,
            errors="raise",
        )

        timestamps = timestamps.dt.tz_localize(
            source_file.timestamp_timezone,
        )

        values = dataframe[interface.values_column]

        for timestamp, value, source_row_number in zip(
            timestamps,
            values,
            batch.source_line_numbers,
        ):
            timestamp_python = timestamp.to_pydatetime()

            if timestamp_python < deployment.valid_from:
                raise ValueError(
                    "Observation timestamp precedes deployment "
                    f"{deployment.deployment_id}: "
                    f"source line {source_row_number}"
                )

            if (
                deployment.valid_to is not None
                and timestamp_python >= deployment.valid_to
            ):
                raise ValueError(
                    "Observation timestamp exceeds deployment "
                    f"{deployment.deployment_id}: "
                    f"source line {source_row_number}"
                )

            if pd.isna(value):
                normalized_value = float("nan")
            else:
                normalized_value = float(value)

            observations.append(
                NormalizedObservation(
                    location_id=deployment.location_id,
                    variable_id=deployment.variable_id,
                    timestamp=timestamp_python,
                    value=normalized_value,
                    interface_id=interface.interface_id,
                    source_row_number=source_row_number,
                )
            )

    return tuple(observations)

HASH_CHUNK_SIZE = 1024 * 1024

@dataclass(frozen=True)
class FileFingerprint:
    """Represent the content identity of a physical source file."""

    file_hash: str
    file_size: int


def fingerprint_file(path: Path) -> FileFingerprint:
    """Calculate a source file's SHA-256 hash and size."""

    digest = sha256()
    file_size = 0

    with path.open("rb") as source:
        while True:
            chunk = source.read(HASH_CHUNK_SIZE)

            if not chunk:
                break

            digest.update(chunk)
            file_size += len(chunk)

    return FileFingerprint(
        file_hash=f"sha256:{digest.hexdigest()}",
        file_size=file_size,
    )

@dataclass(frozen=True)
class FileVersion:
    """Represent an immutable version of a registered source file."""

    file_version_id: int
    file_id: int
    file_hash: str
    file_size: int


def get_or_create_file_version(
    file_id: int,
    fingerprint: FileFingerprint,
) -> FileVersion:
    """Return the file version matching this exact file content."""

    with connect("dendroflow_raw") as connection:
        row = connection.execute(
            """
            INSERT INTO file_versions (
                file_id,
                file_hash,
                file_size
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (file_id, file_hash)
            DO NOTHING
            RETURNING
                file_version_id,
                file_id,
                file_hash,
                file_size
            """,
            (
                file_id,
                fingerprint.file_hash,
                fingerprint.file_size,
            ),
        ).fetchone()

        if row is None:
            row = connection.execute(
                """
                SELECT
                    file_version_id,
                    file_id,
                    file_hash,
                    file_size
                FROM file_versions
                WHERE file_id = %s
                  AND file_hash = %s
                """,
                (
                    file_id,
                    fingerprint.file_hash,
                ),
            ).fetchone()

    if row is None:
        raise RuntimeError(
            "Could not create or retrieve file version "
            f"for file_id={file_id}"
        )

    return FileVersion(
        file_version_id=row[0],
        file_id=row[1],
        file_hash=row[2],
        file_size=row[3],
    )
