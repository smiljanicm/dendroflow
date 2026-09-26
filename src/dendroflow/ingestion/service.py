from dataclasses import dataclass

import psycopg

from .batches import (
    create_ingestion_batch,
    fail_ingestion_batch,
    get_ingestion_batch,
    start_ingestion_batch,
    validate_ingestion_batch_checkpoint,
)
from .conflicts import ObservationConflictError
from .locks import FileIngestionInProgressError, file_ingestion_lock
from .models import (
    FileFingerprint,
    IngestionCounts,
    IngestionError,
    IngestionFileResult,
    IngestionRun,
    ObservationWriteCounts,
)
from .normalization import normalize_batch
from .runs import (
    create_ingestion_run_with_targets,
    finalize_ingestion_run,
    finish_ingestion_run,
    get_completed_ingestion_run,
    get_ingested_interface_ids,
    get_resumable_file_version,
    get_resumable_ingestion_run,
)
from .snapshots import (
    SourceFileChangingError,
    SourceSnapshotUnavailableError,
    capture_source_snapshot,
    load_source_snapshot,
)
from .sources import (
    NoSourceInterfacesError,
    UnknownSourceFileError,
    get_deployments,
    get_source_file,
    get_source_interfaces,
    read_source_file,
)
from .versions import (
    SourceFileRegressionError,
    get_latest_completed_file_size,
    get_or_create_file_version,
)
from .writer import write_ingestion_batch, write_ingestion_batch_with_counts


class IngestionRetryLimitError(RuntimeError):
    """Raised when a batch has exhausted its configured attempts."""


@dataclass
class _IngestionProgress:
    file_id: int
    filepath: str | None = None
    ingestion_run_id: int | None = None
    file_version_id: int | None = None
    snapshot_hash: str | None = None
    resumed: bool | None = None
    counts_available: bool = False
    already_completed: bool = False
    source_rows_examined: int = 0
    observations_inserted: int = 0
    observations_unchanged: int = 0
    repeated_identity_rows: int = 0
    deferred_trailing_bytes: int | None = None
    current_batch_number: int | None = None

    def add_batch_counts(self, counts: ObservationWriteCounts) -> None:
        self.observations_inserted += counts.inserted
        self.observations_unchanged += counts.unchanged
        self.repeated_identity_rows += counts.repeated_identity_rows

    def result(
        self,
        outcome: str,
        error: Exception | None = None,
        *,
        error_category: str | None = None,
    ) -> IngestionFileResult:
        if self.counts_available and not self.already_completed:
            counts = IngestionCounts(
                source_rows_examined=self.source_rows_examined,
                observations_inserted=self.observations_inserted,
                observations_unchanged=self.observations_unchanged,
                repeated_identity_rows=self.repeated_identity_rows,
                deferred_trailing_bytes=self.deferred_trailing_bytes,
            )
        else:
            counts = None

        result_error = None
        if error is not None:
            result_error = IngestionError(
                category=error_category or "unexpected_error",
                message=str(error),
                batch_number=self.current_batch_number,
                source_line=getattr(error, "source_line", None),
            )

        return IngestionFileResult(
            file_id=self.file_id,
            filepath=self.filepath,
            outcome=outcome,
            ingestion_run_id=self.ingestion_run_id,
            file_version_id=self.file_version_id,
            snapshot_hash=self.snapshot_hash,
            resumed=self.resumed,
            counts=counts,
            error=result_error,
        )


def _classify_ingestion_error(error: Exception) -> tuple[str, str]:
    if isinstance(error, FileIngestionInProgressError):
        return "deferred", "file_busy"
    if isinstance(error, SourceFileChangingError):
        return "deferred", "source_changing"
    if isinstance(error, NoSourceInterfacesError):
        return "needs_configuration", "needs_configuration"
    if isinstance(error, (UnknownSourceFileError, FileNotFoundError)):
        return "failed", "source_unavailable"
    if isinstance(error, SourceSnapshotUnavailableError):
        return "failed", "source_snapshot_unavailable"
    if isinstance(error, SourceFileRegressionError):
        return "failed", "source_regression"
    if isinstance(error, ObservationConflictError):
        return "failed", "observation_conflict"
    if isinstance(error, IngestionRetryLimitError):
        return "failed", "retry_limit"
    if isinstance(error, psycopg.Error):
        return "failed", "database_error"
    return "failed", "unexpected_error"


def ingest_file(
    file_id: int,
    *,
    max_attempts: int = 3,
) -> IngestionRun:
    """Ingest one registered source file into RAW."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    with file_ingestion_lock(file_id):
        return _ingest_file(file_id, max_attempts=max_attempts)


def ingest_file_with_report(
    file_id: int,
    *,
    max_attempts: int = 3,
) -> IngestionFileResult:
    """Ingest one file and report the outcome and work from this invocation."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    progress = _IngestionProgress(file_id=file_id)
    try:
        with file_ingestion_lock(file_id):
            run = _ingest_file(
                file_id,
                max_attempts=max_attempts,
                progress=progress,
            )
    except Exception as error: # noqa: BLE001
        # Convert unexpected failures into structured report results.
        outcome, category = _classify_ingestion_error(error)
        return progress.result(
            outcome,
            error,
            error_category=category,
        )

    progress.ingestion_run_id = run.ingestion_run_id
    outcome = "already_completed" if progress.already_completed else "completed"
    return progress.result(outcome)


def _ingest_file(
    file_id: int,
    *,
    max_attempts: int,
    progress: _IngestionProgress | None = None,
) -> IngestionRun:
    """Run ingestion while the caller holds the file lock."""

    source_file = get_source_file(file_id)
    if progress is not None:
        progress.filepath = str(source_file.filepath)
        progress.resumed = False
    interfaces = get_source_interfaces(file_id)

    if not interfaces:
        raise NoSourceInterfacesError(
            f"No source interfaces registered for file_id={file_id}"
        )

    interface_ids = tuple(
        interface.interface_id
        for interface in interfaces
    )

    resumable_context = get_resumable_file_version(
        file_id,
        interface_ids,
    )
    if resumable_context is not None:
        resumable_run, file_version = resumable_context
        if progress is not None:
            progress.resumed = True
        snapshot = load_source_snapshot(
            source_file.filepath,
            file_id,
            FileFingerprint(
                file_hash=file_version.file_hash,
                file_size=file_version.file_size,
            ),
        )
        if progress is not None:
            progress.counts_available = True
            progress.snapshot_hash = file_version.file_hash
            progress.deferred_trailing_bytes = None
    else:
        snapshot = capture_source_snapshot(
            source_file.filepath,
            file_id,
        )
        if progress is not None:
            progress.counts_available = True
            progress.snapshot_hash = snapshot.fingerprint.file_hash
            progress.deferred_trailing_bytes = getattr(
                snapshot,
                "deferred_bytes",
                None,
            )
        latest_size = get_latest_completed_file_size(file_id)
        if (
            latest_size is not None
            and snapshot.fingerprint.file_size < latest_size
        ):
            raise SourceFileRegressionError(
                "Captured source is smaller than the latest completed "
                f"snapshot for file_id={file_id}: "
                f"captured_size={snapshot.fingerprint.file_size}, "
                f"latest_completed_size={latest_size}"
            )
        file_version = get_or_create_file_version(
            file_id,
            snapshot.fingerprint,
        )
        resumable_run = None

    if progress is not None:
        progress.file_version_id = file_version.file_version_id
        progress.snapshot_hash = file_version.file_hash

    if resumable_run is None:
        completed_run = get_completed_ingestion_run(
            file_version.file_version_id,
            interface_ids,
        )

        if completed_run is not None:
            if progress is not None:
                progress.already_completed = True
                progress.ingestion_run_id = completed_run.ingestion_run_id
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

    if resumable_run is None:
        resumable_run = get_resumable_ingestion_run(
            file_version.file_version_id,
            interface_ids,
        )
        if progress is not None and resumable_run is not None:
            progress.resumed = True

    if progress is not None and resumable_run is None:
        progress.resumed = False

    if resumable_run is not None:
        run = resumable_run
    else:
        run = create_ingestion_run_with_targets(
            file_version.file_version_id,
            interfaces,
        )

    if progress is not None:
        progress.ingestion_run_id = run.ingestion_run_id

    try:
        batch_number = 0

        for tabular_batch in read_source_file(
            file_id,
            source_path=snapshot.snapshot_path,
        ):
            if len(tabular_batch.dataframe) == 0:
                continue

            batch_number += 1
            if progress is not None:
                progress.source_rows_examined += len(tabular_batch.dataframe)
                progress.current_batch_number = batch_number

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
                    if progress is not None:
                        progress.current_batch_number = None
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
                raise IngestionRetryLimitError(
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

                    if progress is None:
                        ingestion_batch = write_ingestion_batch(
                            ingestion_batch,
                            observations,
                        )
                    else:
                        write_result = write_ingestion_batch_with_counts(
                            ingestion_batch,
                            observations,
                        )
                        ingestion_batch = write_result.batch
                        progress.add_batch_counts(write_result.counts)

                    if progress is not None:
                        progress.current_batch_number = None

                    break

                except Exception as error:
                    ingestion_batch = fail_ingestion_batch(
                        ingestion_batch.ingestion_batch_id,
                        f"{type(error).__name__}: {error}",
                    )

                    if (
                        isinstance(error, ObservationConflictError)
                        or ingestion_batch.attempt_count >= max_attempts
                    ):
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
