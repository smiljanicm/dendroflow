import math

from dendroflow.database import connect

from .batches import complete_ingestion_batch
from .conflicts import (
    ObservationConflictError,
    deduplicate_observations,
    observation_identity,
    values_equal,
)
from .models import (
    IngestionBatch,
    IngestionBatchWriteResult,
    NormalizedObservation,
    ObservationWriteCounts,
    ValueConflictSample,
)

_MAX_CONFLICT_SAMPLES = 5


def _report_value(value: float) -> float | str:
    """Keep the JSON report valid when a conflicting value is NaN or infinite."""

    numeric = float(value)
    return numeric if math.isfinite(numeric) else str(numeric)


def insert_raw_observations(
    connection,
    ingestion_run_id: int,
    observations: tuple[NormalizedObservation, ...],
) -> None:
    """Insert normalized observations within an existing transaction."""

    insert_raw_observations_with_counts(
        connection,
        ingestion_run_id,
        observations,
    )


def insert_raw_observations_with_counts(
    connection,
    ingestion_run_id: int,
    observations: tuple[NormalizedObservation, ...],
) -> ObservationWriteCounts:
    """Insert observations and count inserts, matches, and repeats."""

    inserted_count = 0
    unchanged_count = 0
    conflict_count = 0
    conflict_samples: list[ValueConflictSample] = []

    with connection.cursor() as cursor:
        unique_observations, repeated_count = deduplicate_observations(
            observations
        )
        for observation in unique_observations:
            identity = observation_identity(observation)
            cursor.execute(
                """
                SELECT interface_id, value
                FROM raw_observations
                WHERE location_id = %s
                  AND variable_id = %s
                  AND timestamp = %s
                FOR UPDATE
                """,
                identity,
            )
            existing = cursor.fetchone()

            if existing is not None:
                conflict = _handle_existing_observation(
                    cursor, existing, observation, ingestion_run_id,
                )
                if conflict is None:
                    unchanged_count += 1
                else:
                    conflict_count += 1
                    if len(conflict_samples) < _MAX_CONFLICT_SAMPLES:
                        conflict_samples.append(conflict)
                continue

            cursor.execute(
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
                ON CONFLICT (
                    location_id,
                    variable_id,
                    timestamp
                ) DO NOTHING
                RETURNING observation_id
                """,
                (
                    observation.location_id,
                    observation.variable_id,
                    observation.timestamp,
                    observation.value,
                    observation.interface_id,
                    ingestion_run_id,
                    observation.source_row_number,
                ),
            )
            inserted = cursor.fetchone()

            if inserted is not None:
                inserted_count += 1
            else:
                cursor.execute(
                    """
                    SELECT interface_id, value
                    FROM raw_observations
                    WHERE location_id = %s
                      AND variable_id = %s
                      AND timestamp = %s
                    FOR UPDATE
                    """,
                    identity,
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise RuntimeError(
                        "Observation identity conflicted during insert but "
                        f"could not be read back: identity={identity}"
                    )
                conflict = _handle_existing_observation(
                    cursor, existing, observation, ingestion_run_id,
                )
                if conflict is None:
                    unchanged_count += 1
                else:
                    conflict_count += 1
                    if len(conflict_samples) < _MAX_CONFLICT_SAMPLES:
                        conflict_samples.append(conflict)

    return ObservationWriteCounts(
        inserted=inserted_count,
        unchanged=unchanged_count,
        repeated_identity_rows=repeated_count,
        value_conflicts=conflict_count,
        conflict_samples=tuple(conflict_samples),
    )


def _handle_existing_observation(
    cursor,
    existing: tuple[int, float],
    incoming: NormalizedObservation,
    ingestion_run_id: int,
) -> ValueConflictSample | None:
    identity = observation_identity(incoming)
    existing_interface_id, existing_value = existing
    if values_equal(float(existing_value), incoming.value):
        return None

    if existing_interface_id == incoming.interface_id:
        raise ObservationConflictError(
            "Observation value conflict: "
            f"identity={identity}, "
            f"stored_value={existing_value!r}, "
            f"incoming_value={incoming.value!r}, "
            f"stored_interface_id={existing_interface_id}, "
            f"incoming_interface_id={incoming.interface_id}, "
            f"incoming_source_line={incoming.source_row_number}",
            source_line=incoming.source_row_number,
        )

    # Both versions are preserved: the first RAW value and this audit record.
    # This runs in the same transaction as the observation batch checkpoint.
    cursor.execute(
        """
        INSERT INTO raw_observation_conflicts (
            ingestion_run_id, location_id, variable_id, timestamp,
            stored_interface_id, incoming_interface_id,
            stored_value, incoming_value, incoming_source_row_number
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            ingestion_run_id, incoming.location_id, incoming.variable_id,
            incoming.timestamp, existing_interface_id, incoming.interface_id,
            existing_value, incoming.value, incoming.source_row_number,
        ),
    )
    return ValueConflictSample(
        location_id=incoming.location_id,
        variable_id=incoming.variable_id,
        timestamp=incoming.timestamp.isoformat(),
        stored_value=_report_value(existing_value),
        incoming_value=_report_value(incoming.value),
        stored_interface_id=existing_interface_id,
        incoming_interface_id=incoming.interface_id,
        incoming_source_line=incoming.source_row_number,
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
        return complete_ingestion_batch(
            connection,
            batch.ingestion_batch_id,
        )

def write_ingestion_batch_with_counts(
    batch: IngestionBatch,
    observations: tuple[NormalizedObservation, ...],
) -> IngestionBatchWriteResult:
    """Write a batch atomically and return counts after commit."""

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
        counts = insert_raw_observations_with_counts(
            connection,
            batch.ingestion_run_id,
            observations,
        )

        completed_batch = complete_ingestion_batch(
            connection,
            batch.ingestion_batch_id,
        )

    return IngestionBatchWriteResult(
        batch=completed_batch,
        counts=counts,
    )
