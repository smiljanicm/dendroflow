"""Read RAW file registrations for discovery comparison."""

from dendroflow.database import connect

from .models import RegisteredFile


def get_registered_files() -> tuple[RegisteredFile, ...]:
    """Return file paths and interface counts without changing the database."""

    with connect("dendroflow_raw") as connection:
        rows = connection.execute(
            """
            SELECT
                files.file_id,
                files.filepath,
                COUNT(sensor_file_interfaces.interface_id)
            FROM files
            LEFT JOIN sensor_file_interfaces
                ON sensor_file_interfaces.file_id = files.file_id
            GROUP BY files.file_id, files.filepath
            ORDER BY files.file_id
            """
        ).fetchall()

    return tuple(
        RegisteredFile(
            file_id=row[0],
            filepath=row[1],
            interface_count=row[2],
        )
        for row in rows
    )
