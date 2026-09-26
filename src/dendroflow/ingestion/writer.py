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
    NormalizedObservation,
)


def insert_raw_observations(
    connection,
    ingestion_run_id: int,
    observations: tuple[NormalizedObservation, ...],
) -> None:
    """Insert normalized observations within an existing transaction."""

    with connection.cursor() as cursor:
        unique_observations, _ = deduplicate_observations(observations)
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
                _validate_existing_observation(existing, observation)
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

            if inserted is None:
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
                _validate_existing_observation(existing, observation)


def _validate_existing_observation(
    existing: tuple[int, float],
    incoming: NormalizedObservation,
) -> None:
    identity = observation_identity(incoming)
    existing_interface_id, existing_value = existing
    if existing_interface_id != incoming.interface_id:
        raise ObservationConflictError(
            "Observation source-mapping conflict: "
            f"identity={identity}, "
            f"stored_interface_id={existing_interface_id}, "
            f"incoming_interface_id={incoming.interface_id}, "
            f"incoming_source_line={incoming.source_row_number}"
        )
    if not values_equal(float(existing_value), incoming.value):
        raise ObservationConflictError(
            "Observation value conflict: "
            f"identity={identity}, "
            f"stored_value={existing_value!r}, "
            f"incoming_value={incoming.value!r}, "
            f"incoming_source_line={incoming.source_row_number}"
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
