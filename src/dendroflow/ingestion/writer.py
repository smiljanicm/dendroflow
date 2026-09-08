from dendroflow.database import connect

from .batches import complete_ingestion_batch
from .models import (
    IngestionBatch,
    NormalizedObservation,
)


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

