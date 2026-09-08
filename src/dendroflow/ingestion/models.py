from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SourceFile:
    """Represent a source file registered in DendroFlow."""

    file_id: int
    filepath: Path
    timestamp_timezone: str
    timestamp_format: str
    reader_config: dict[str, Any]


@dataclass(frozen=True)
class SourceInterface:
    """Represent one measurement interface registered for a source file."""

    interface_id: int
    file_id: int
    deployment_id: int
    values_column: str
    timestamp_column: str
    unit: str | None


@dataclass(frozen=True)
class Deployment:
    """Represent deployment metadata needed during ingestion."""

    deployment_id: int
    sensor_id: int
    location_id: int
    variable_id: int
    valid_from: datetime
    valid_to: datetime | None


@dataclass(frozen=True)
class NormalizedObservation:
    """Represent one observation ready for RAW ingestion."""

    location_id: int
    variable_id: int
    timestamp: datetime
    value: float
    interface_id: int
    source_row_number: int


@dataclass(frozen=True)
class FileFingerprint:
    """Represent the content identity of a physical source file."""

    file_hash: str
    file_size: int


@dataclass(frozen=True)
class FileVersion:
    """Represent an immutable version of a registered source file."""

    file_version_id: int
    file_id: int
    file_hash: str
    file_size: int


@dataclass(frozen=True)
class IngestionRun:
    """Represent one DendroFlow ingestion execution."""

    ingestion_run_id: int
    started_at: datetime
    finished_at: datetime | None
    status: str


@dataclass(frozen=True)
class IngestionBatch:
    """Represent one checkpointed ingestion batch."""

    ingestion_batch_id: int
    ingestion_run_id: int
    file_version_id: int
    batch_number: int
    source_line_start: int
    source_line_end: int
    row_count: int
    status: str
    attempt_count: int
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
