from collections.abc import Iterator
from pathlib import Path
from hashlib import sha256

import pandas as pd

from dendroflow.database import connect
from dendroflow.readers import reader_from_config
from dendroflow.tabular import TabularBatch

from .models import (
    Deployment,
    FileFingerprint,
    FileVersion,
    IngestionBatch,
    IngestionRun,
    NormalizedObservation,
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

    reader = reader_from_config(source_file.reader_config)

    yield from reader.read(source_file.filepath)

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

def create_ingestion_run() -> IngestionRun:
    """Create a new running ingestion run."""

    with connect("dendroflow_raw") as connection:
        row = connection.execute(
            """
            INSERT INTO ingestion_runs (
                started_at,
                status
            )
            VALUES (
                CURRENT_TIMESTAMP,
                'running'
            )
            RETURNING
                ingestion_run_id,
                started_at,
                finished_at,
                status
            """
        ).fetchone()

    if row is None:
        raise RuntimeError("Could not create ingestion run")

    return IngestionRun(
        ingestion_run_id=row[0],
        started_at=row[1],
        finished_at=row[2],
        status=row[3],
    )

def finish_ingestion_run(
    ingestion_run_id: int,
    status: str,
) -> IngestionRun:
    """Finish a running ingestion run."""

    if status not in {"completed", "failed"}:
        raise ValueError(
            "Finished ingestion status must be "
            "'completed' or 'failed'"
        )

    with connect("dendroflow_raw") as connection:
        row = connection.execute(
            """
            UPDATE ingestion_runs
            SET
                finished_at = CURRENT_TIMESTAMP,
                status = %s
            WHERE ingestion_run_id = %s
              AND status = 'running'
            RETURNING
                ingestion_run_id,
                started_at,
                finished_at,
                status
            """,
            (
                status,
                ingestion_run_id,
            ),
        ).fetchone()

    if row is None:
        raise ValueError(
            f"Unknown or non-running ingestion run: "
            f"{ingestion_run_id}"
        )

    return IngestionRun(
        ingestion_run_id=row[0],
        started_at=row[1],
        finished_at=row[2],
        status=row[3],
    )

def _ingestion_batch_from_row(row) -> IngestionBatch:
    return IngestionBatch(
        ingestion_batch_id=row[0],
        ingestion_run_id=row[1],
        file_version_id=row[2],
        batch_number=row[3],
        source_line_start=row[4],
        source_line_end=row[5],
        row_count=row[6],
        status=row[7],
        attempt_count=row[8],
        started_at=row[9],
        finished_at=row[10],
        error_message=row[11],
    )

def create_ingestion_batch(
    ingestion_run_id: int,
    file_version_id: int,
    batch_number: int,
    source_line_start: int,
    source_line_end: int,
    row_count: int,
) -> IngestionBatch:
    """Create a pending ingestion batch."""

    with connect("dendroflow_raw") as connection:
        row = connection.execute(
            """
            INSERT INTO ingestion_batches (
                ingestion_run_id,
                file_version_id,
                batch_number,
                source_line_start,
                source_line_end,
                row_count
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING
                ingestion_batch_id,
                ingestion_run_id,
                file_version_id,
                batch_number,
                source_line_start,
                source_line_end,
                row_count,
                status,
                attempt_count,
                started_at,
                finished_at,
                error_message
            """,
            (
                ingestion_run_id,
                file_version_id,
                batch_number,
                source_line_start,
                source_line_end,
                row_count,
            ),
        ).fetchone()

    if row is None:
        raise RuntimeError("Could not create ingestion batch")

    return _ingestion_batch_from_row(row)

def start_ingestion_batch(
    ingestion_batch_id: int,
) -> IngestionBatch:
    """Start or retry an ingestion batch."""

    with connect("dendroflow_raw") as connection:
        row = connection.execute(
            """
            UPDATE ingestion_batches
            SET
                status = 'running',
                attempt_count = attempt_count + 1,
                started_at = CURRENT_TIMESTAMP,
                finished_at = NULL,
                error_message = NULL
            WHERE ingestion_batch_id = %s
              AND status IN ('pending', 'failed')
            RETURNING
                ingestion_batch_id,
                ingestion_run_id,
                file_version_id,
                batch_number,
                source_line_start,
                source_line_end,
                row_count,
                status,
                attempt_count,
                started_at,
                finished_at,
                error_message
            """,
            (ingestion_batch_id,),
        ).fetchone()

    if row is None:
        raise ValueError(
            "Unknown batch or batch cannot be started: "
            f"{ingestion_batch_id}"
        )

    return _ingestion_batch_from_row(row)

def fail_ingestion_batch(
    ingestion_batch_id: int,
    error_message: str,
) -> IngestionBatch:
    """Mark a running ingestion batch as failed."""

    with connect("dendroflow_raw") as connection:
        row = connection.execute(
            """
            UPDATE ingestion_batches
            SET
                status = 'failed',
                finished_at = CURRENT_TIMESTAMP,
                error_message = %s
            WHERE ingestion_batch_id = %s
              AND status = 'running'
            RETURNING
                ingestion_batch_id,
                ingestion_run_id,
                file_version_id,
                batch_number,
                source_line_start,
                source_line_end,
                row_count,
                status,
                attempt_count,
                started_at,
                finished_at,
                error_message
            """,
            (
                error_message,
                ingestion_batch_id,
            ),
        ).fetchone()

    if row is None:
        raise ValueError(
            "Unknown or non-running ingestion batch: "
            f"{ingestion_batch_id}"
        )

    return _ingestion_batch_from_row(row)

def complete_ingestion_batch(
    connection,
    ingestion_batch_id: int,
) -> IngestionBatch:
    """Mark a batch completed within an existing transaction."""

    row = connection.execute(
        """
        UPDATE ingestion_batches
        SET
            status = 'completed',
            finished_at = CURRENT_TIMESTAMP,
            error_message = NULL
        WHERE ingestion_batch_id = %s
          AND status = 'running'
        RETURNING
            ingestion_batch_id,
            ingestion_run_id,
            file_version_id,
            batch_number,
            source_line_start,
            source_line_end,
            row_count,
            status,
            attempt_count,
            started_at,
            finished_at,
            error_message
        """,
        (ingestion_batch_id,),
    ).fetchone()

    if row is None:
        raise ValueError(
            "Unknown or non-running ingestion batch: "
            f"{ingestion_batch_id}"
        )

    return _ingestion_batch_from_row(row)

def insert_raw_observations(
    connection,
    ingestion_run_id: int,
    observations: tuple[NormalizedObservation, ...],
) -> None:
    """Insert normalized observations within an existing transaction."""

    rows = [
        (
            observation.location_id,
            observation.variable_id,
            observation.timestamp,
            observation.value,
            observation.interface_id,
            ingestion_run_id,
            observation.source_row_number,
        )
        for observation in observations
    ]

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO raw_observations (
                location_id,
                variable_id,
                timestamp,
                value,
                interface_id,
                ingestion_run_id,
                source_row_number
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            rows,
        )

def write_ingestion_batch(
    batch: IngestionBatch,
    observations: tuple[NormalizedObservation, ...],
) -> IngestionBatch:
    """Write one running ingestion batch atomically."""

    if batch.status != "running":
        raise ValueError(
            "Ingestion batch must be running before it can be written"
        )

    if not observations:
        raise ValueError(
            "Cannot write an ingestion batch with no observations"
        )

    source_lines = [
        observation.source_row_number
        for observation in observations
    ]

    if (
        min(source_lines) < batch.source_line_start
        or max(source_lines) > batch.source_line_end
    ):
        raise ValueError(
            "Observation source lines fall outside ingestion batch range"
        )

    with connect("dendroflow_raw") as connection:
        insert_raw_observations(
            connection,
            batch.ingestion_run_id,
            observations,
        )

        completed_batch = complete_ingestion_batch(
            connection,
            batch.ingestion_batch_id,
        )

    return completed_batch

def finalize_ingestion_run(
    ingestion_run_id: int,
    file_version_id: int,
    interfaces: tuple[SourceInterface, ...],
) -> IngestionRun:
    """Finalize a successful ingestion atomically."""

    if not interfaces:
        raise ValueError(
            "Cannot finalize ingestion without source interfaces"
        )

    with connect("dendroflow_raw") as connection:
        batch_counts = connection.execute(
            """
            SELECT
                COUNT(*) AS total_batches,
                COUNT(*) FILTER (
                    WHERE status <> 'completed'
                ) AS incomplete_batches
            FROM ingestion_batches
            WHERE ingestion_run_id = %s
            """,
            (ingestion_run_id,),
        ).fetchone()

        if batch_counts is None or batch_counts[0] == 0:
            raise ValueError(
                f"Ingestion run has no batches: {ingestion_run_id}"
            )

        if batch_counts[1] != 0:
            raise ValueError(
                f"Ingestion run has incomplete batches: "
                f"{ingestion_run_id}"
            )

        rows = [
            (
                ingestion_run_id,
                file_version_id,
                interface.interface_id,
            )
            for interface in interfaces
        ]

        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO ingestion_interfaces (
                    ingestion_run_id,
                    file_version_id,
                    interface_id
                )
                VALUES (%s, %s, %s)
                """,
                rows,
            )

        row = connection.execute(
            """
            UPDATE ingestion_runs
            SET
                finished_at = CURRENT_TIMESTAMP,
                status = 'completed'
            WHERE ingestion_run_id = %s
              AND status = 'running'
            RETURNING
                ingestion_run_id,
                started_at,
                finished_at,
                status
            """,
            (ingestion_run_id,),
        ).fetchone()

        if row is None:
            raise ValueError(
                "Unknown or non-running ingestion run: "
                f"{ingestion_run_id}"
            )

    return IngestionRun(
        ingestion_run_id=row[0],
        started_at=row[1],
        finished_at=row[2],
        status=row[3],
    )

def get_ingested_interface_ids(
    file_version_id: int,
) -> set[int]:
    """Return interfaces successfully ingested for a file version."""

    with connect("dendroflow_raw") as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT
                ii.interface_id
            FROM ingestion_interfaces ii
            JOIN ingestion_runs ir
                ON ir.ingestion_run_id = ii.ingestion_run_id
            WHERE ii.file_version_id = %s
              AND ir.status = 'completed'
            """,
            (file_version_id,),
        ).fetchall()

    return {row[0] for row in rows}

def get_completed_ingestion_run(
    file_version_id: int,
    interface_ids: tuple[int, ...],
) -> IngestionRun | None:
    """Return a completed run containing all requested interfaces."""

    if not interface_ids:
        return None

    with connect("dendroflow_raw") as connection:
        row = connection.execute(
            """
            SELECT
                ir.ingestion_run_id,
                ir.started_at,
                ir.finished_at,
                ir.status
            FROM ingestion_runs ir
            JOIN ingestion_interfaces ii
                ON ii.ingestion_run_id = ir.ingestion_run_id
            WHERE ii.file_version_id = %s
              AND ii.interface_id = ANY(%s)
              AND ir.status = 'completed'
            GROUP BY
                ir.ingestion_run_id,
                ir.started_at,
                ir.finished_at,
                ir.status
            HAVING COUNT(DISTINCT ii.interface_id) = %s
            ORDER BY ir.finished_at DESC
            LIMIT 1
            """,
            (
                file_version_id,
                list(interface_ids),
                len(interface_ids),
            ),
        ).fetchone()

    if row is None:
        return None

    return IngestionRun(
        ingestion_run_id=row[0],
        started_at=row[1],
        finished_at=row[2],
        status=row[3],
    )

def ingest_file(
    file_id: int,
    *,
    max_attempts: int = 3,
) -> IngestionRun:
    """Ingest one registered source file into RAW."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    source_file = get_source_file(file_id)

    fingerprint = fingerprint_file(source_file.filepath)

    file_version = get_or_create_file_version(
        file_id,
        fingerprint,
    )

    interfaces = get_source_interfaces(file_id)

    if not interfaces:
        raise ValueError(
            f"No source interfaces registered for file_id={file_id}"
        )

    interface_ids = tuple(
        interface.interface_id
        for interface in interfaces
    )

    completed_run = get_completed_ingestion_run(
        file_version.file_version_id,
        interface_ids,
    )

    if completed_run is not None:
        return completed_run

    ingested_interface_ids = get_ingested_interface_ids(
       file_version.file_version_id
    )

    already_ingested = (
        set(interface_ids)
        & ingested_interface_ids
    )

    if already_ingested:
        raise ValueError(
            "File version is partially already ingested for "
            f"interfaces {sorted(already_ingested)}. "
            "Resume/selective ingestion is required."
        )

    deployment_ids = tuple(
        interface.deployment_id
        for interface in interfaces
    )

    deployments = get_deployments(deployment_ids)

    resumable_run = get_resumable_ingestion_run(
        file_version.file_version_id,
        interface_ids,
    )

    if resumable_run is not None:
        run = resumable_run
    else:
        run = create_ingestion_run_with_targets(
            file_version.file_version_id,
            interfaces,
        )

    try:
        batch_number = 0

        for tabular_batch in read_source_file(file_id):
            if len(tabular_batch.dataframe) == 0:
                continue

            batch_number += 1

            ingestion_batch = get_ingestion_batch(
                ingestion_run_id=run.ingestion_run_id,
                file_version_id=file_version.file_version_id,
                batch_number=batch_number,
            )

            if ingestion_batch is None:
                ingestion_batch = create_ingestion_batch(
                    ingestion_run_id=run.ingestion_run_id,
                    file_version_id=file_version.file_version_id,
                    batch_number=batch_number,
                    source_line_start=tabular_batch.source_line_numbers[0],
                    source_line_end=tabular_batch.source_line_numbers[-1],
                    row_count=len(tabular_batch.dataframe),
                )

            else:
                validate_ingestion_batch_checkpoint(
                    ingestion_batch,
                    tabular_batch,
                )

                if ingestion_batch.status == "completed":
                    continue

                if ingestion_batch.status == "running":
                    ingestion_batch = fail_ingestion_batch(
                        ingestion_batch.ingestion_batch_id,
                        "Interrupted ingestion detected during resume",
                    )

                if ingestion_batch.status not in {
                    "pending",
                    "failed",
                }:
                    raise ValueError(
                        "Cannot resume ingestion batch "
                        f"{ingestion_batch.ingestion_batch_id} "
                        f"with status={ingestion_batch.status}"
                    )

            if ingestion_batch.attempt_count >= max_attempts:
                raise RuntimeError(
                    "Ingestion batch has already reached the maximum "
                    f"number of attempts: batch_number={batch_number}, "
                    f"attempt_count={ingestion_batch.attempt_count}"
                )

            while ingestion_batch.attempt_count < max_attempts:
                ingestion_batch = start_ingestion_batch(
                    ingestion_batch.ingestion_batch_id
                )

                try:
                    observations = normalize_batch(
                        tabular_batch,
                        source_file,
                        interfaces,
                        deployments,
                    )

                    ingestion_batch = write_ingestion_batch(
                        ingestion_batch,
                        observations,
                    )

                    break

                except Exception as error:
                    ingestion_batch = fail_ingestion_batch(
                        ingestion_batch.ingestion_batch_id,
                        f"{type(error).__name__}: {error}",
                    )

                    if ingestion_batch.attempt_count >= max_attempts:
                        raise

        return finalize_ingestion_run(
            ingestion_run_id=run.ingestion_run_id,
            file_version_id=file_version.file_version_id,
            interfaces=interfaces,
        )

    except Exception:
        try:
            finish_ingestion_run(
                run.ingestion_run_id,
                "failed",
            )
        except ValueError:
            pass

        raise

def _create_ingestion_run(connection) -> IngestionRun:
    row = connection.execute(
        """
        INSERT INTO ingestion_runs (
            started_at,
            status
        )
        VALUES (
            CURRENT_TIMESTAMP,
            'running'
        )
        RETURNING
            ingestion_run_id,
            started_at,
            finished_at,
            status
        """
    ).fetchone()

    return IngestionRun(
        ingestion_run_id=row[0],
        started_at=row[1],
        finished_at=row[2],
        status=row[3],
    )

def create_ingestion_run() -> IngestionRun:
    with connect("dendroflow_raw") as connection:
        return _create_ingestion_run(connection)

def create_ingestion_run_with_targets(
    file_version_id: int,
    interfaces: tuple[SourceInterface, ...],
) -> IngestionRun:
    """Create an ingestion run together with its immutable target snapshot."""

    if not interfaces:
        raise ValueError(
            "Cannot create ingestion run without interfaces"
        )

    with connect("dendroflow_raw") as connection:
        run = _create_ingestion_run(connection)

        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO ingestion_targets (
                    ingestion_run_id,
                    file_version_id,
                    interface_id
                )
                VALUES (%s, %s, %s)
                """,
                [
                    (
                        run.ingestion_run_id,
                        file_version_id,
                        interface.interface_id,
                    )
                    for interface in interfaces
                ],
            )

    return run

def get_resumable_ingestion_run(
    file_version_id: int,
    interface_ids: tuple[int, ...],
) -> IngestionRun | None:
    """Return a running ingestion run with exactly the requested targets."""

    requested_interface_ids = tuple(
        sorted(set(interface_ids))
    )

    if not requested_interface_ids:
        return None

    with connect("dendroflow_raw") as connection:
        row = connection.execute(
            """
            SELECT
                ir.ingestion_run_id,
                ir.started_at,
                ir.finished_at,
                ir.status
            FROM ingestion_runs ir
            JOIN ingestion_targets it
                ON it.ingestion_run_id = ir.ingestion_run_id
            WHERE ir.status = 'running'
            GROUP BY
                ir.ingestion_run_id,
                ir.started_at,
                ir.finished_at,
                ir.status
            HAVING
                COUNT(*) = %s
                AND COUNT(*) FILTER (
                    WHERE it.file_version_id = %s
                      AND it.interface_id = ANY(%s)
                ) = %s
            ORDER BY ir.started_at DESC
            LIMIT 1
            """,
            (
                len(requested_interface_ids),
                file_version_id,
                list(requested_interface_ids),
                len(requested_interface_ids),
            ),
        ).fetchone()

    if row is None:
        return None

    return IngestionRun(
        ingestion_run_id=row[0],
        started_at=row[1],
        finished_at=row[2],
        status=row[3],
    )

def get_ingestion_batch(
    ingestion_run_id: int,
    file_version_id: int,
    batch_number: int,
) -> IngestionBatch | None:
    """Return an existing batch checkpoint, if one exists."""

    with connect("dendroflow_raw") as connection:
        row = connection.execute(
            """
            SELECT
                ingestion_batch_id,
                ingestion_run_id,
                file_version_id,
                batch_number,
                source_line_start,
                source_line_end,
                row_count,
                status,
                attempt_count,
                started_at,
                finished_at,
                error_message
            FROM ingestion_batches
            WHERE ingestion_run_id = %s
              AND file_version_id = %s
              AND batch_number = %s
            """,
            (
                ingestion_run_id,
                file_version_id,
                batch_number,
            ),
        ).fetchone()

    if row is None:
        return None

    return _ingestion_batch_from_row(row)

def validate_ingestion_batch_checkpoint(
    ingestion_batch: IngestionBatch,
    tabular_batch: TabularBatch,
) -> None:
    """Ensure an existing checkpoint still describes the current source batch."""

    if not tabular_batch.source_line_numbers:
        raise ValueError("Tabular batch has no source line numbers")

    expected_start = tabular_batch.source_line_numbers[0]
    expected_end = tabular_batch.source_line_numbers[-1]
    expected_count = len(tabular_batch.dataframe)

    if (
        ingestion_batch.source_line_start != expected_start
        or ingestion_batch.source_line_end != expected_end
        or ingestion_batch.row_count != expected_count
    ):
        raise ValueError(
            "Existing ingestion batch checkpoint does not match "
            "the current reader batch: "
            f"batch_number={ingestion_batch.batch_number}"
        )
