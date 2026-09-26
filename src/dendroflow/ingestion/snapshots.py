"""Capture stable, immutable snapshots of registered source files."""

from __future__ import annotations

import hashlib
import math
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .models import FileFingerprint

COPY_CHUNK_SIZE = 1024 * 1024
STAT_POLL_SECONDS = 0.1
DEFAULT_SETTLE_SECONDS = 1.0
DEFAULT_STABILITY_TIMEOUT_SECONDS = 60.0
DEFAULT_CAPTURE_ATTEMPTS = 3


class SourceFileChangingError(RuntimeError):
    """Raised when a stable source snapshot cannot be captured."""


class SourceSnapshotUnavailableError(RuntimeError):
    """Raised when an interrupted run's retained snapshot is unavailable."""


@dataclass(frozen=True)
class SourceSnapshot:
    """A content-addressed snapshot and its source capture details."""

    source_path: Path
    snapshot_path: Path
    fingerprint: FileFingerprint
    captured_size: int
    deferred_bytes: int


def load_source_snapshot(
    source_path: Path,
    file_id: int,
    fingerprint: FileFingerprint,
) -> SourceSnapshot:
    """Load and verify the immutable snapshot referenced by a file version."""

    digest_name = fingerprint.file_hash.removeprefix("sha256:")
    if (
        len(digest_name) != 64
        or any(character not in "0123456789abcdef" for character in digest_name)
    ):
        raise SourceSnapshotUnavailableError(
            f"Invalid stored snapshot hash for file_id={file_id}"
        )

    path = snapshot_directory() / str(file_id) / f"{digest_name}.snapshot"
    if not path.is_file():
        raise SourceSnapshotUnavailableError(
            "Cannot resume ingestion because its staged snapshot is missing: "
            f"file_id={file_id}, snapshot={path}"
        )

    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(COPY_CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
    actual_hash = f"sha256:{digest.hexdigest()}"
    if size != fingerprint.file_size or actual_hash != fingerprint.file_hash:
        raise SourceSnapshotUnavailableError(
            "Cannot resume ingestion because its staged snapshot failed "
            f"verification: file_id={file_id}, snapshot={path}"
        )

    return SourceSnapshot(
        source_path=source_path.resolve(),
        snapshot_path=path,
        fingerprint=fingerprint,
        captured_size=size,
        deferred_bytes=0,
    )


def _setting(name: str, default: str) -> str:
    """Read a setting from the process environment or project .env file."""

    value = os.getenv(name)
    if value is not None:
        return value

    project_root = Path(
        os.getenv("DENDROFLOW_ROOT", Path.cwd())
    ).expanduser()
    env_path = project_root / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            key, separator, setting = line.strip().partition("=")
            if separator and key.strip() == name:
                return setting.strip()

    return default


def snapshot_directory() -> Path:
    """Return the persistent snapshot directory."""

    raw_path = _setting(
        "DENDROFLOW_SNAPSHOT_DIR",
        "~/.local/state/dendroflow/snapshots",
    )
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise ValueError("DENDROFLOW_SNAPSHOT_DIR must be an absolute path")
    return path


def file_settle_seconds() -> float:
    """Return how long file size and modification time must remain stable."""

    raw_value = _setting(
        "DENDROFLOW_FILE_SETTLE_SECONDS",
        str(DEFAULT_SETTLE_SECONDS),
    )
    try:
        seconds = float(raw_value)
    except ValueError as error:
        raise ValueError(
            "DENDROFLOW_FILE_SETTLE_SECONDS must be a non-negative number"
        ) from error
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(
            "DENDROFLOW_FILE_SETTLE_SECONDS must be a non-negative number"
        )
    return seconds


def _signature(stat_result: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        stat_result.st_dev,
        stat_result.st_ino,
        stat_result.st_size,
        stat_result.st_mtime_ns,
        stat_result.st_ctime_ns,
    )


def _wait_until_stable(
    source_path: Path,
    *,
    settle_seconds: float,
    timeout_seconds: float,
) -> os.stat_result:
    deadline = time.monotonic() + timeout_seconds
    previous = source_path.stat()
    stable_since = time.monotonic()

    while time.monotonic() < deadline:
        if time.monotonic() - stable_since >= settle_seconds:
            return previous

        time.sleep(min(STAT_POLL_SECONDS, max(0.0, deadline - time.monotonic())))
        current = source_path.stat()
        if _signature(current) != _signature(previous):
            previous = current
            stable_since = time.monotonic()

    raise SourceFileChangingError(
        f"Source file did not remain stable for {settle_seconds:g} seconds: "
        f"{source_path}"
    )


def _capture_once(
    source_path: Path,
    destination_dir: Path,
    stable_stat: os.stat_result,
) -> tuple[Path, str, int, int] | None:
    """Copy the stable size, retaining complete newline-terminated records."""

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".snapshot-",
        suffix=".tmp",
        dir=destination_dir,
    )
    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(descriptor, "wb") as target, source_path.open("rb") as source:
            before = os.fstat(source.fileno())
            invalid_capture = _signature(before) != _signature(stable_stat)
            remaining = stable_stat.st_size
            copied = 0
            last_newline_end = 0
            while not invalid_capture and remaining:
                chunk = source.read(min(COPY_CHUNK_SIZE, remaining))
                if not chunk:
                    invalid_capture = True
                    break
                target.write(chunk)
                copied += len(chunk)
                remaining -= len(chunk)
                newline = chunk.rfind(b"\n")
                if newline >= 0:
                    last_newline_end = copied - len(chunk) + newline + 1

            if not invalid_capture:
                target.flush()
                after = os.fstat(source.fileno())
                path_after = source_path.stat()
                invalid_capture = (
                    _signature(after) != _signature(stable_stat)
                    or _signature(path_after) != _signature(stable_stat)
                )

        if invalid_capture:
            temporary_path.unlink(missing_ok=True)
            return None

        deferred_bytes = stable_stat.st_size - last_newline_end
        with temporary_path.open("r+b") as snapshot:
            snapshot.truncate(last_newline_end)
            snapshot.seek(0)
            digest = hashlib.sha256()
            size = 0
            while chunk := snapshot.read(COPY_CHUNK_SIZE):
                digest.update(chunk)
                size += len(chunk)
            snapshot.flush()
            os.fsync(snapshot.fileno())

        return temporary_path, f"sha256:{digest.hexdigest()}", size, deferred_bytes
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def capture_source_snapshot(
    source_path: Path,
    file_id: int,
    *,
    directory: Path | None = None,
    settle_seconds: float | None = None,
    stability_timeout_seconds: float = DEFAULT_STABILITY_TIMEOUT_SECONDS,
    max_attempts: int = DEFAULT_CAPTURE_ATTEMPTS,
) -> SourceSnapshot:
    """Capture stable bytes to an atomic, content-addressed snapshot file.

    Incomplete trailing physical lines are omitted and counted as deferred.
    """

    if file_id < 1:
        raise ValueError("file_id must be positive")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    source_path = source_path.resolve(strict=True)
    staging_dir = (directory or snapshot_directory()) / str(file_id)
    staging_dir.mkdir(parents=True, exist_ok=True)
    settle = file_settle_seconds() if settle_seconds is None else settle_seconds
    if not math.isfinite(settle) or settle < 0:
        raise ValueError("settle_seconds must be a non-negative number")
    if (
        not math.isfinite(stability_timeout_seconds)
        or stability_timeout_seconds <= 0
        or settle > stability_timeout_seconds
    ):
        raise ValueError(
            "stability_timeout_seconds must be positive and at least "
            "settle_seconds"
        )

    for _attempt in range(max_attempts):
        stable_stat = _wait_until_stable(
            source_path,
            settle_seconds=settle,
            timeout_seconds=stability_timeout_seconds,
        )
        captured = _capture_once(source_path, staging_dir, stable_stat)
        if captured is None:
            continue

        temporary_path, file_hash, file_size, deferred_bytes = captured
        snapshot_path = staging_dir / f"{file_hash.removeprefix('sha256:')}.snapshot"
        try:
            if snapshot_path.exists():
                digest = hashlib.sha256()
                existing_size = 0
                with snapshot_path.open("rb") as existing:
                    while chunk := existing.read(COPY_CHUNK_SIZE):
                        digest.update(chunk)
                        existing_size += len(chunk)
                if (
                    existing_size != file_size
                    or f"sha256:{digest.hexdigest()}" != file_hash
                ):
                    raise RuntimeError(
                        f"Corrupt staged snapshot already exists: {snapshot_path}"
                    )
                temporary_path.unlink()
            else:
                os.replace(temporary_path, snapshot_path)
        finally:
            temporary_path.unlink(missing_ok=True)

        return SourceSnapshot(
            source_path=source_path,
            snapshot_path=snapshot_path,
            fingerprint=FileFingerprint(
                file_hash=file_hash,
                file_size=file_size,
            ),
            captured_size=stable_stat.st_size,
            deferred_bytes=deferred_bytes,
        )

    raise SourceFileChangingError(
        f"Source file changed while being captured after {max_attempts} attempts: "
        f"{source_path}"
    )
