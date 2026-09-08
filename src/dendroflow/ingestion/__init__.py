# from pathlib import Path
# from hashlib import sha256

from dendroflow.database import connect
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

from .sources import (
    get_deployments,
    get_source_file,
    get_source_interfaces,
    read_source_file,
)

from .normalization import normalize_batch

from .versions import (
    fingerprint_file,
    get_or_create_file_version,
)

from .runs import (
    create_ingestion_run,
    create_ingestion_run_with_targets,
    finalize_ingestion_run,
    finish_ingestion_run,
    get_completed_ingestion_run,
    get_ingested_interface_ids,
    get_resumable_ingestion_run,
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
