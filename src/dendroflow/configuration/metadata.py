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


def find_sensor_models(
    *,
    manufacturer: str | None = None,
    model: str | None = None,
) -> tuple[MetadataRow, ...]:
    """Find sensor models matching the supplied identifying fields."""

    conditions: list[str] = []
    parameters: list[object] = []

    if manufacturer is not None:
        conditions.append("manufacturer = %s")
        parameters.append(manufacturer)

    if model is not None:
        conditions.append("model = %s")
        parameters.append(model)

    if not conditions:
        raise ValueError(
            "sensor model lookup requires manufacturer or model"
        )

    where_clause = " AND ".join(conditions)

    with connect("dendroflow_metadata") as connection:
        rows = connection.execute(
            f"""
            SELECT
                sensor_model_id,
                model,
                manufacturer,
                sensor_type_id
            FROM sensor_models
            WHERE {where_clause}
            ORDER BY sensor_model_id
            """,
            tuple(parameters),
        ).fetchall()

    return tuple(
        MetadataRow(
            database_id=row[0],
            values={
                "model": row[1],
                "manufacturer": row[2],
                "sensor_type_id": row[3],
            },
        )
        for row in rows
    )


def find_sensors(
    *,
    serial_number: str | None = None,
    sensor_model_id: int | None = None,
) -> tuple[MetadataRow, ...]:
    """Find sensors matching the supplied identifying fields."""

    conditions: list[str] = []
    parameters: list[object] = []

    if serial_number is not None:
        conditions.append("serial_number = %s")
        parameters.append(serial_number)

    if sensor_model_id is not None:
        conditions.append("sensor_model_id = %s")
        parameters.append(sensor_model_id)

    if not conditions:
        raise ValueError(
            "sensor lookup requires serial_number or sensor_model_id"
        )

    where_clause = " AND ".join(conditions)

    with connect("dendroflow_metadata") as connection:
        rows = connection.execute(
            f"""
            SELECT
                sensor_id,
                sensor_model_id,
                serial_number,
                description
            FROM sensors
            WHERE {where_clause}
            ORDER BY sensor_id
            """,
            tuple(parameters),
        ).fetchall()

    return tuple(
        MetadataRow(
            database_id=row[0],
            values={
                "sensor_model_id": row[1],
                "serial_number": row[2],
                "description": row[3],
            },
        )
        for row in rows
    )

