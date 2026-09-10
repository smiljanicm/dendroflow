from dataclasses import dataclass

from dendroflow.database import connect


@dataclass(frozen=True)
class RawRow:
    database_id: int
    values: dict[str, object]


def find_file(filepath: str) -> RawRow | None:
    """Find a configured RAW file by filepath."""

    with connect("dendroflow_raw") as connection:
        row = connection.execute(
            """
            SELECT
                file_id,
                filepath,
                timestamp_timezone,
                timestamp_format,
                reader_config
            FROM files
            WHERE filepath = %s
            """,
            (filepath,),
        ).fetchone()

    if row is None:
        return None

    return RawRow(
        database_id=row[0],
        values={
            "filepath": row[1],
            "timestamp_timezone": row[2],
            "timestamp_format": row[3],
            "reader_config": row[4],
        },
    )


def find_file_interfaces(
    file_id: int,
) -> tuple[RawRow, ...]:
    """Return configured interfaces for a RAW file."""

    if file_id <= 0:
        raise ValueError(
            "file_id must be greater than zero"
        )

    with connect("dendroflow_raw") as connection:
        rows = connection.execute(
            """
            SELECT
                interface_id,
                file_id,
                deployment_id,
                values_column,
                timestamp_column,
                unit
            FROM sensor_file_interfaces
            WHERE file_id = %s
            ORDER BY interface_id
            """,
            (file_id,),
        ).fetchall()

    return tuple(
        RawRow(
            database_id=row[0],
            values={
                "file_id": row[1],
                "deployment_id": row[2],
                "values_column": row[3],
                "timestamp_column": row[4],
                "unit": row[5],
            },
        )
        for row in rows
    )

