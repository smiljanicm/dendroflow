from hashlib import sha256
from pathlib import Path

from dendroflow.database import connect

from .models import (
    FileFingerprint,
    FileVersion,
)

HASH_CHUNK_SIZE = 1024 * 1024


class SourceFileRegressionError(RuntimeError):
    """Raised when a captured source is smaller than accepted content."""


def fingerprint_file(path: Path) -> FileFingerprint:
    """Calculate a source file's SHA-256 hash and size."""

    digest = sha256()
    file_size = 0

    with path.open("rb") as source:
        while True:
            chunk = source.read(HASH_CHUNK_SIZE)

            if not chunk:
                break

            digest.update(chunk)
            file_size += len(chunk)

    return FileFingerprint(
        file_hash=f"sha256:{digest.hexdigest()}",
        file_size=file_size,
    )


def get_latest_completed_file_size(file_id: int) -> int | None:
    """Return the largest snapshot size used by a completed run."""

    with connect("dendroflow_raw") as connection:
        row = connection.execute(
            """
            SELECT MAX(fv.file_size)
            FROM file_versions AS fv
            JOIN ingestion_targets AS targets
                USING (file_version_id)
            JOIN ingestion_runs AS runs
                USING (ingestion_run_id)
            WHERE fv.file_id = %s
              AND runs.status = 'completed'
            """,
            (file_id,),
        ).fetchone()

    return None if row is None else row[0]


def get_or_create_file_version(
    file_id: int,
    fingerprint: FileFingerprint,
) -> FileVersion:
    """Return the file version matching this exact file content."""

    with connect("dendroflow_raw") as connection:
        row = connection.execute(
            """
            INSERT INTO file_versions (
                file_id,
                file_hash,
                file_size
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (file_id, file_hash)
            DO NOTHING
            RETURNING
                file_version_id,
                file_id,
                file_hash,
                file_size
            """,
            (
                file_id,
                fingerprint.file_hash,
                fingerprint.file_size,
            ),
        ).fetchone()

        if row is None:
            row = connection.execute(
                """
                SELECT
                    file_version_id,
                    file_id,
                    file_hash,
                    file_size
                FROM file_versions
                WHERE file_id = %s
                  AND file_hash = %s
                """,
                (
                    file_id,
                    fingerprint.file_hash,
                ),
            ).fetchone()

    if row is None:
        raise RuntimeError(
            "Could not create or retrieve file version "
            f"for file_id={file_id}"
        )

    return FileVersion(
        file_version_id=row[0],
        file_id=row[1],
        file_hash=row[2],
        file_size=row[3],
    )
