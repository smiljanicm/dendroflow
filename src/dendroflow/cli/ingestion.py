"""Run registered source-file ingestion from the command line."""

import argparse
import json
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import asdict

import psycopg

from dendroflow.config import get_database_target
from dendroflow.database import use_database_target
from dendroflow.ingestion.models import IngestionFileResult
from dendroflow.ingestion.service import (
    IngestionProgressEvent,
    ingest_file_with_report,
)
from dendroflow.ingestion.sources import get_source_file_ids

OUTCOMES = (
    "completed",
    "already_completed",
    "deferred",
    "needs_configuration",
    "failed",
)

_HEARTBEAT_SECONDS = 15
_BATCH_REPORT_SECONDS = 10


class _ProgressDisplay:
    """Show live activity without mixing it into result stdout."""

    def __init__(self, file_id: int) -> None:
        self.file_id = file_id
        self.started_at = time.monotonic()
        self.last_report_at = self.started_at
        self.last_batch: int | None = None
        self.last_rows = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)

    @contextmanager
    def running(self) -> Iterator[None]:
        print(f"File {self.file_id}: starting ingestion...", file=sys.stderr, flush=True)
        self.thread.start()
        try:
            yield
        finally:
            self.stop.set()
            self.thread.join()

    def _heartbeat(self) -> None:
        while not self.stop.wait(_HEARTBEAT_SECONDS):
            elapsed = int(time.monotonic() - self.started_at)
            detail = (
                "preparing source"
                if self.last_batch is None
                else f"last processed batch={self.last_batch}, rows examined={self.last_rows}"
            )
            print(
                f"File {self.file_id}: working ({elapsed}s elapsed; {detail})",
                file=sys.stderr,
                flush=True,
            )

    def __call__(self, event: IngestionProgressEvent) -> None:
        if event.phase == "source_loaded" and event.filepath is not None:
            print(
                f"File {self.file_id}: filepath: {event.filepath}",
                file=sys.stderr,
                flush=True,
            )
        elif event.phase == "snapshot":
            print(
                f"File {self.file_id}: preparing stable source snapshot...",
                file=sys.stderr,
                flush=True,
            )
        elif event.phase == "snapshot_ready":
            print(
                f"File {self.file_id}: snapshot ready; checking ingestion state...",
                file=sys.stderr,
                flush=True,
            )
        elif event.phase in {"batch_completed", "batch_reused"}:
            self.last_batch = event.batch_number
            self.last_rows = event.source_rows_examined
            now = time.monotonic()
            if (
                event.batch_number == 1
                or now - self.last_report_at >= _BATCH_REPORT_SECONDS
            ):
                label = (
                    "reused batch" if event.phase == "batch_reused" else "batch"
                )
                print(
                    f"File {self.file_id}: {label} {event.batch_number}; "
                    f"rows examined={event.source_rows_examined}; "
                    f"inserted={event.observations_inserted}, "
                    f"unchanged={event.observations_unchanged}, "
                    f"value_conflicts={event.value_conflicts}",
                    file=sys.stderr,
                    flush=True,
                )
                self.last_report_at = now


def positive_integer(value: str) -> int:
    """Parse an argparse value that must be greater than zero."""

    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _summary(results: list[IngestionFileResult]) -> dict[str, int]:
    summary = {
        "selected": len(results),
        **{outcome: 0 for outcome in OUTCOMES},
    }
    for result in results:
        summary[result.outcome] += 1
    return summary


def _result_document(result: IngestionFileResult) -> dict[str, object]:
    return asdict(result)


def _exit_code(results: list[IngestionFileResult]) -> int:
    if any(
        result.outcome in {"failed", "needs_configuration"}
        for result in results
    ):
        return 1
    if any(result.outcome == "deferred" for result in results):
        return 3
    return 0


def _format_text(
    results: list[IngestionFileResult],
    environment: str,
) -> tuple[str, list[str]]:
    lines = [f"Target environment: {environment}"]
    diagnostics = []

    for result in results:
        lines.append(f"File {result.file_id}: {result.outcome}")
        if result.filepath is not None:
            lines.append(f"  Path: {result.filepath}")
        if result.ingestion_run_id is not None or result.file_version_id is not None:
            lines.append(
                f"  Run: {result.ingestion_run_id}; "
                f"file version: {result.file_version_id}"
            )
        if result.snapshot_hash is not None:
            lines.append(f"  Snapshot: {result.snapshot_hash}")
        if result.resumed is not None:
            lines.append(f"  Resumed: {str(result.resumed).lower()}")
        if result.counts is not None:
            counts = result.counts
            lines.append(f"  Rows examined: {counts.source_rows_examined}")
            lines.append(
                "  Observations: "
                f"inserted={counts.observations_inserted}, "
                f"unchanged={counts.observations_unchanged}, "
                f"repeated={counts.repeated_identity_rows}, "
                f"value_conflicts={counts.value_conflicts}"
            )
            for sample in counts.conflict_samples:
                lines.append(
                    "  Value conflict kept: "
                    f"location={sample.location_id}, variable={sample.variable_id}, "
                    f"timestamp={sample.timestamp}, "
                    f"stored={sample.stored_value} "
                    f"(interface {sample.stored_interface_id}), "
                    f"incoming={sample.incoming_value} "
                    f"(interface {sample.incoming_interface_id}, "
                    f"source line {sample.incoming_source_line})"
                )
            if counts.value_conflicts > len(counts.conflict_samples):
                lines.append(
                    "  Additional value conflicts recorded: "
                    f"{counts.value_conflicts - len(counts.conflict_samples)}"
                )
            if counts.deferred_trailing_bytes is not None:
                lines.append(
                    "  Deferred trailing bytes: "
                    f"{counts.deferred_trailing_bytes}"
                )
        if result.error is not None:
            error = result.error
            context = []
            if error.batch_number is not None:
                context.append(f"batch {error.batch_number}")
            if error.source_line is not None:
                context.append(f"source line {error.source_line}")
            suffix = f" ({', '.join(context)})" if context else ""
            diagnostics.append(
                f"File {result.file_id}: [{error.category}] "
                f"{error.message}{suffix}"
            )

    summary = _summary(results)
    lines.append(
        "Ingestion summary: "
        + ", ".join(
            f"{key}={summary[key]}"
            for key in ("selected", *OUTCOMES)
        )
    )
    return "\n".join(lines), diagnostics


def ingest(args: argparse.Namespace) -> int:
    """Preflight and ingest the requested source files."""

    try:
        target = get_database_target()
    except KeyboardInterrupt:
        print("Ingestion interrupted.", file=sys.stderr)
        return 130
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Invalid database target: {error}", file=sys.stderr)
        return 2

    try:
        with use_database_target(target):
            registered_ids = set(get_source_file_ids())
    except KeyboardInterrupt:
        print("Ingestion interrupted.", file=sys.stderr)
        return 130
    except (OSError, RuntimeError, ValueError, psycopg.Error) as error:
        print(f"Unable to resolve ingestion selection: {error}", file=sys.stderr)
        return 2

    if args.all:
        file_ids = sorted(registered_ids)
    else:
        requested_ids = set(args.file_id)
        missing_ids = sorted(requested_ids - registered_ids)
        if missing_ids:
            missing = ", ".join(str(file_id) for file_id in missing_ids)
            print(f"Unknown file ID(s): {missing}", file=sys.stderr)
            return 2
        file_ids = sorted(requested_ids)

    results: list[IngestionFileResult] = []
    snapshot_option = {"keep_snapshot": True} if args.keep_snapshot else {}
    try:
        with use_database_target(target):
            for file_id in file_ids:
                display = (
                    _ProgressDisplay(file_id)
                    if args.progress or not args.json
                    else None
                )
                with display.running() if display is not None else nullcontext():
                    if display is None:
                        result = ingest_file_with_report(
                            file_id, max_attempts=args.max_attempts,
                            **snapshot_option,
                        )
                    else:
                        result = ingest_file_with_report(
                            file_id,
                            max_attempts=args.max_attempts,
                            on_progress=display,
                            **snapshot_option,
                        )
                    results.append(result)
    except KeyboardInterrupt:
        print("Ingestion interrupted.", file=sys.stderr)
        return 130

    if args.json:
        document = {
            "schema_version": 1,
            "target_environment": target.environment,
            "summary": _summary(results),
            "files": [_result_document(result) for result in results],
        }
        print(json.dumps(document, indent=2, ensure_ascii=False))
    else:
        text, diagnostics = _format_text(results, target.environment)
        print(text)
        for diagnostic in diagnostics:
            print(diagnostic, file=sys.stderr)

    return _exit_code(results)
