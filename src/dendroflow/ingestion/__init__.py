from dendroflow.database import connect

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

from .batches import (
    complete_ingestion_batch,
    create_ingestion_batch,
    fail_ingestion_batch,
    get_ingestion_batch,
    start_ingestion_batch,
    validate_ingestion_batch_checkpoint,
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

