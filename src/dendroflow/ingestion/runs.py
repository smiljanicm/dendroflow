from dendroflow.database import connect

from .models import (
    IngestionRun,
    SourceInterface,
)


def _ingestion_run_from_row(row) -> IngestionRun:
    """Convert a database row into an ingestion run."""

    return IngestionRun(
        ingestion_run_id=row[0],
        started_at=row[1],
        finished_at=row[2],
        status=row[3],
    )


def _create_ingestion_run(connection) -> IngestionRun:
    row = connection.execute(
        """
        INSERT INTO ingestion_runs (
            started_at,
            status
        )
        VALUES (
            CURRENT_TIMESTAMP,
            'running'
        )
        RETURNING
            ingestion_run_id,
            started_at,
            finished_at,
            status
        """
    ).fetchone()

    return _ingestion_run_from_row(row)


def create_ingestion_run() -> IngestionRun:
    with connect("dendroflow_raw") as connection:
        return _create_ingestion_run(connection)


def finish_ingestion_run(
    ingestion_run_id: int,
    status: str,
) -> IngestionRun:
    """Finish a running ingestion run."""

    if status not in {"completed", "failed"}:
        raise ValueError(
            "Finished ingestion status must be "
            "'completed' or 'failed'"
        )

    with connect("dendroflow_raw") as connection:
        row = connection.execute(
            """
            UPDATE ingestion_runs
            SET
                finished_at = CURRENT_TIMESTAMP,
                status = %s
            WHERE ingestion_run_id = %s
              AND status = 'running'
            RETURNING
                ingestion_run_id,
                started_at,
                finished_at,
                status
            """,
            (
                status,
                ingestion_run_id,
            ),
        ).fetchone()

    if row is None:
        raise ValueError(
            f"Unknown or non-running ingestion run: "
            f"{ingestion_run_id}"
        )

    return _ingestion_run_from_row(row)


def create_ingestion_run_with_targets(
    file_version_id: int,
    interfaces: tuple[SourceInterface, ...],
) -> IngestionRun:
    """Create an ingestion run together with its immutable target snapshot."""

    if not interfaces:
        raise ValueError(
            "Cannot create ingestion run without interfaces"
        )

    with connect("dendroflow_raw") as connection:
        run = _create_ingestion_run(connection)

        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO ingestion_targets (
                    ingestion_run_id,
                    file_version_id,
                    interface_id
                )
                VALUES (%s, %s, %s)
                """,
                [
                    (
                        run.ingestion_run_id,
                        file_version_id,
                        interface.interface_id,
                    )
                    for interface in interfaces
                ],
            )

    return run


def get_completed_ingestion_run(
    file_version_id: int,
    interface_ids: tuple[int, ...],
) -> IngestionRun | None:
    """Return a completed run containing all requested interfaces."""

    if not interface_ids:
        return None

    with connect("dendroflow_raw") as connection:
        row = connection.execute(
            """
            SELECT
                ir.ingestion_run_id,
                ir.started_at,
                ir.finished_at,
                ir.status
            FROM ingestion_runs ir
            JOIN ingestion_interfaces ii
                ON ii.ingestion_run_id = ir.ingestion_run_id
            WHERE ii.file_version_id = %s
              AND ii.interface_id = ANY(%s)
              AND ir.status = 'completed'
            GROUP BY
                ir.ingestion_run_id,
                ir.started_at,
                ir.finished_at,
                ir.status
            HAVING COUNT(DISTINCT ii.interface_id) = %s
            ORDER BY ir.finished_at DESC
            LIMIT 1
            """,
            (
                file_version_id,
                list(interface_ids),
                len(interface_ids),
            ),
        ).fetchone()

    if row is None:
        return None

    return _ingestion_run_from_row(row)


def get_ingested_interface_ids(
    file_version_id: int,
) -> set[int]:
    """Return interfaces successfully ingested for a file version."""

    with connect("dendroflow_raw") as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT
                ii.interface_id
            FROM ingestion_interfaces ii
            JOIN ingestion_runs ir
                ON ir.ingestion_run_id = ii.ingestion_run_id
            WHERE ii.file_version_id = %s
              AND ir.status = 'completed'
            """,
            (file_version_id,),
        ).fetchall()

    return {row[0] for row in rows}


def get_resumable_ingestion_run(
    file_version_id: int,
    interface_ids: tuple[int, ...],
) -> IngestionRun | None:
    """Return a running ingestion run with exactly the requested targets."""

    requested_interface_ids = tuple(
        sorted(set(interface_ids))
    )

    if not requested_interface_ids:
        return None

    with connect("dendroflow_raw") as connection:
        row = connection.execute(
            """
            SELECT
                ir.ingestion_run_id,
                ir.started_at,
                ir.finished_at,
                ir.status
            FROM ingestion_runs ir
            JOIN ingestion_targets it
                ON it.ingestion_run_id = ir.ingestion_run_id
            WHERE ir.status = 'running'
            GROUP BY
                ir.ingestion_run_id,
                ir.started_at,
                ir.finished_at,
                ir.status
            HAVING
                COUNT(*) = %s
                AND COUNT(*) FILTER (
                    WHERE it.file_version_id = %s
                      AND it.interface_id = ANY(%s)
                ) = %s
            ORDER BY ir.started_at DESC
            LIMIT 1
            """,
            (
                len(requested_interface_ids),
                file_version_id,
                list(requested_interface_ids),
                len(requested_interface_ids),
            ),
        ).fetchone()

    if row is None:
        return None

    return _ingestion_run_from_row(row)


def finalize_ingestion_run(
    ingestion_run_id: int,
    file_version_id: int,
    interfaces: tuple[SourceInterface, ...],
) -> IngestionRun:
    """Finalize a successful ingestion atomically."""

    if not interfaces:
        raise ValueError(
            "Cannot finalize ingestion without source interfaces"
        )

    with connect("dendroflow_raw") as connection:
        batch_counts = connection.execute(
            """
            SELECT
                COUNT(*) AS total_batches,
                COUNT(*) FILTER (
                    WHERE status <> 'completed'
                ) AS incomplete_batches
            FROM ingestion_batches
            WHERE ingestion_run_id = %s
            """,
            (ingestion_run_id,),
        ).fetchone()

        if batch_counts is None or batch_counts[0] == 0:
            raise ValueError(
                f"Ingestion run has no batches: {ingestion_run_id}"
            )

        if batch_counts[1] != 0:
            raise ValueError(
                f"Ingestion run has incomplete batches: "
                f"{ingestion_run_id}"
            )

        rows = [
            (
                ingestion_run_id,
                file_version_id,
                interface.interface_id,
            )
            for interface in interfaces
        ]

        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO ingestion_interfaces (
                    ingestion_run_id,
                    file_version_id,
                    interface_id
                )
                VALUES (%s, %s, %s)
                """,
                rows,
            )

        row = connection.execute(
            """
            UPDATE ingestion_runs
            SET
                finished_at = CURRENT_TIMESTAMP,
                status = 'completed'
            WHERE ingestion_run_id = %s
              AND status = 'running'
            RETURNING
                ingestion_run_id,
                started_at,
                finished_at,
                status
            """,
            (ingestion_run_id,),
        ).fetchone()

        if row is None:
            raise ValueError(
                "Unknown or non-running ingestion run: "
                f"{ingestion_run_id}"
            )

    return _ingestion_run_from_row(row)

