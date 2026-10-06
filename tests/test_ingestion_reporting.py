from contextlib import nullcontext
from datetime import datetime, timezone

import psycopg
import pytest

from dendroflow.ingestion import FileIngestionInProgressError, SourceFile
from dendroflow.ingestion.conflicts import ObservationConflictError
from dendroflow.ingestion.models import (
    NormalizedObservation,
    ObservationWriteCounts,
    ValueConflictSample,
)
from dendroflow.ingestion.service import (
    IngestionRetryLimitError,
    _IngestionProgress,
    ingest_file_with_report,
)
from dendroflow.ingestion.snapshots import (
    SourceFileChangingError,
    SourceSnapshotUnavailableError,
)
from dendroflow.ingestion.sources import UnknownSourceFileError
from dendroflow.ingestion.versions import SourceFileRegressionError
from dendroflow.ingestion.writer import (
    _report_value,
    insert_raw_observations_with_counts,
)


def test_insert_observations_reports_counts_for_committed_work():
    existing_timestamp = datetime(2026, 3, 19, tzinfo=timezone.utc)
    new_timestamp = datetime(2026, 3, 19, 0, 15, tzinfo=timezone.utc)
    existing = NormalizedObservation(
        location_id=3,
        variable_id=1,
        timestamp=existing_timestamp,
        value=10.5,
        interface_id=4,
        source_row_number=5,
    )
    repeated = NormalizedObservation(
        location_id=3,
        variable_id=1,
        timestamp=existing_timestamp,
        value=10.5,
        interface_id=4,
        source_row_number=6,
    )
    new = NormalizedObservation(
        location_id=3,
        variable_id=1,
        timestamp=new_timestamp,
        value=11.2,
        interface_id=4,
        source_row_number=7,
    )

    class FakeCursor:
        def __init__(self):
            self.result = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, parameters):
            self.result = None
            if query.lstrip().startswith("SELECT interface_id, value"):
                if parameters[2] == existing_timestamp:
                    self.result = (4, 10.5)
            elif query.lstrip().startswith("INSERT INTO raw_observations"):
                self.result = (1,)

        def fetchone(self):
            return self.result

    cursor = FakeCursor()

    class FakeConnection:
        def cursor(self):
            return cursor

    counts = insert_raw_observations_with_counts(
        FakeConnection(),
        ingestion_run_id=9,
        observations=(existing, repeated, new),
    )

    assert counts.inserted == 1
    assert counts.unchanged == 1
    assert counts.repeated_identity_rows == 1


def test_equal_cross_file_overlap_keeps_first_provenance_and_inserts_gaps():
    timestamp = datetime(2026, 3, 19, tzinfo=timezone.utc)
    later = datetime(2026, 3, 19, 0, 15, tzinfo=timezone.utc)
    latest = datetime(2026, 3, 19, 0, 30, tzinfo=timezone.utc)
    rows = {(3, 1, timestamp): (4, 10.5)}
    audits = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, parameters):
            self.result = None
            if query.lstrip().startswith("SELECT interface_id, value"):
                self.result = rows.get(tuple(parameters))
            elif query.lstrip().startswith("INSERT INTO raw_observations"):
                identity = tuple(parameters[:3])
                if identity not in rows:
                    rows[identity] = (parameters[4], parameters[3])
                    self.result = (2,)
            elif query.lstrip().startswith("INSERT INTO raw_observation_conflicts"):
                audits.append(parameters)

        def fetchone(self):
            return self.result

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    def observation(at, value, interface_id=9):
        return NormalizedObservation(
            location_id=3,
            variable_id=1,
            timestamp=at,
            value=value,
            interface_id=interface_id,
            source_row_number=7,
        )

    counts = insert_raw_observations_with_counts(
        FakeConnection(), 12,
        (observation(timestamp, 10.5), observation(later, 11.2)),
    )

    assert (counts.inserted, counts.unchanged) == (1, 1)
    assert rows[(3, 1, timestamp)] == (4, 10.5)
    assert rows[(3, 1, later)] == (9, 11.2)

    counts = insert_raw_observations_with_counts(
        FakeConnection(), 12,
        (observation(timestamp, 10.6), observation(latest, 11.3)),
    )
    assert (counts.inserted, counts.unchanged, counts.value_conflicts) == (1, 0, 1)
    assert counts.conflict_samples[0].incoming_source_line == 7
    assert rows[(3, 1, timestamp)] == (4, 10.5)
    assert rows[(3, 1, latest)] == (9, 11.3)
    assert audits == [(12, 3, 1, timestamp, 4, 9, 10.5, 10.6, 7)]

    with pytest.raises(ObservationConflictError, match="value conflict"):
        insert_raw_observations_with_counts(
            FakeConnection(), 12, (observation(timestamp, 10.6, 4),),
        )
    assert len(audits) == 1


def test_conflict_report_accumulates_all_batches_but_bounds_examples():
    progress = _IngestionProgress(file_id=3, counts_available=True)
    for index in range(8):
        progress.add_batch_counts(ObservationWriteCounts(
            inserted=1, unchanged=2, repeated_identity_rows=0,
            value_conflicts=1,
            conflict_samples=(ValueConflictSample(
                location_id=4, variable_id=1,
                timestamp=f"2024-06-18T14:{index:02d}:00+01:00",
                stored_value=6721.562, incoming_value=6721.563,
                stored_interface_id=9, incoming_interface_id=14,
                incoming_source_line=30533 + index,
            ),),
        ))
    result = progress.result("completed")
    assert result.counts.observations_inserted == 8
    assert result.counts.observations_unchanged == 16
    assert result.counts.value_conflicts == 8
    assert len(result.counts.conflict_samples) == 5


def test_nonfinite_conflict_sample_values_are_valid_json_strings():
    assert _report_value(float("nan")) == "nan"
    assert _report_value(float("inf")) == "inf"


def test_report_classifies_a_busy_file_without_reading_it(monkeypatch):
    def busy_lock(file_id):
        raise FileIngestionInProgressError(f"file_id={file_id} is busy")

    monkeypatch.setattr(
        "dendroflow.ingestion.service.file_ingestion_lock",
        busy_lock,
    )

    result = ingest_file_with_report(17)

    assert result.outcome == "deferred"
    assert result.error.category == "file_busy"
    assert result.filepath is None
    assert result.counts is None


def test_report_marks_a_registered_file_without_interfaces(
    monkeypatch,
    tmp_path,
):
    source_file = SourceFile(
        file_id=21,
        filepath=tmp_path / "unconfigured.csv",
        timestamp_timezone="UTC",
        timestamp_format="%Y-%m-%d %H:%M:%S",
        reader_config={},
    )
    monkeypatch.setattr(
        "dendroflow.ingestion.service.file_ingestion_lock",
        lambda file_id: nullcontext(),
    )
    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_source_file",
        lambda file_id: source_file,
    )
    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_source_interfaces",
        lambda file_id: (),
    )

    result = ingest_file_with_report(21)

    assert result.outcome == "needs_configuration"
    assert result.filepath == str(source_file.filepath)
    assert result.error.category == "needs_configuration"
    assert result.counts is None


@pytest.mark.parametrize(
    ("error", "outcome", "category"),
    [
        (
            SourceFileChangingError("source is changing"),
            "deferred",
            "source_changing",
        ),
        (
            UnknownSourceFileError("Unknown file_id: 42"),
            "failed",
            "source_unavailable",
        ),
        (FileNotFoundError("missing source"), "failed", "source_unavailable"),
        (
            SourceSnapshotUnavailableError("snapshot missing"),
            "failed",
            "source_snapshot_unavailable",
        ),
        (
            SourceFileRegressionError("source became smaller"),
            "failed",
            "source_regression",
        ),
        (
            ObservationConflictError("value conflict", source_line=8),
            "failed",
            "observation_conflict",
        ),
        (
            IngestionRetryLimitError("retry limit reached"),
            "failed",
            "retry_limit",
        ),
        (psycopg.Error("database unavailable"), "failed", "database_error"),
        (RuntimeError("unexpected"), "failed", "unexpected_error"),
    ],
)
def test_report_classifies_pre_ingestion_errors(
    monkeypatch,
    error,
    outcome,
    category,
):
    monkeypatch.setattr(
        "dendroflow.ingestion.service.file_ingestion_lock",
        lambda file_id: nullcontext(),
    )

    def fail_to_load(file_id):
        raise error

    monkeypatch.setattr(
        "dendroflow.ingestion.service.get_source_file",
        fail_to_load,
    )

    result = ingest_file_with_report(42)

    assert result.outcome == outcome
    assert result.error.category == category
    assert result.counts is None
    if category == "observation_conflict":
        assert result.error.source_line == 8
