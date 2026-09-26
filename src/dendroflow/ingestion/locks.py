from collections.abc import Iterator
from contextlib import contextmanager

from dendroflow.database import connect


class FileIngestionInProgressError(RuntimeError):
    """Raised when another worker already holds a file's ingestion lock."""


@contextmanager
def file_ingestion_lock(file_id: int) -> Iterator[None]:
    """Hold a PostgreSQL session lock for one registered source file."""

    connection = connect("dendroflow_raw")
    lock_name = f"dendroflow:raw-ingestion:file:{file_id}"
    try:
        acquired = connection.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
            (lock_name,),
        ).fetchone()[0]
        connection.commit()
        if not acquired:
            raise FileIngestionInProgressError(
                "Ingestion is already running for "
                f"file_id={file_id}; retry after the active worker finishes"
            )

        yield
    finally:
        # PostgreSQL releases session-level advisory locks when this connection
        # closes, including when ingestion raises or the process is interrupted.
        connection.close()
