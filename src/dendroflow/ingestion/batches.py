from dendroflow.database import connect
from dendroflow.tabular import TabularBatch

from .models import IngestionBatch


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

