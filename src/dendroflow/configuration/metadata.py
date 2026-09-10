from dataclasses import dataclass

from dendroflow.database import connect


@dataclass(frozen=True)
class MetadataRow:
    database_id: int
    values: dict[str, object]


def find_site(site_code: str) -> MetadataRow | None:
    with connect("dendroflow_metadata") as connection:
        row = connection.execute(
            """
            SELECT
                site_id,
                site_code,
                name,
                description,
                latitude,
                longitude,
                parent_id
            FROM sites
            WHERE site_code = %s
            """,
            (site_code,),
        ).fetchone()

    if row is None:
        return None

    return MetadataRow(
        database_id=row[0],
        values={
            "site_code": row[1],
            "name": row[2],
            "description": row[3],
            "latitude": row[4],
            "longitude": row[5],
            "parent_id": row[6],
        },
    )


def find_location_type(type_: str) -> MetadataRow | None:
    with connect("dendroflow_metadata") as connection:
        row = connection.execute(
            """
            SELECT
                location_type_id,
                type,
                description
            FROM location_types
            WHERE type = %s
            """,
            (type_,),
        ).fetchone()

    if row is None:
        return None

    return MetadataRow(
        database_id=row[0],
        values={
            "type": row[1],
            "description": row[2],
        },
    )


def find_sensor_type(type_: str) -> MetadataRow | None:
    with connect("dendroflow_metadata") as connection:
        row = connection.execute(
            """
            SELECT
                sensor_type_id,
                type,
                description
            FROM sensor_types
            WHERE type = %s
            """,
            (type_,),
        ).fetchone()

    if row is None:
        return None

    return MetadataRow(
        database_id=row[0],
        values={
            "type": row[1],
            "description": row[2],
        },
    )


def find_variable(variable: str) -> MetadataRow | None:
    with connect("dendroflow_metadata") as connection:
        row = connection.execute(
            """
            SELECT
                variable_id,
                variable,
                derived,
                description
            FROM variables
            WHERE variable = %s
            """,
            (variable,),
        ).fetchone()

    if row is None:
        return None

    return MetadataRow(
        database_id=row[0],
        values={
            "variable": row[1],
            "derived": row[2],
            "description": row[3],
        },
    )


