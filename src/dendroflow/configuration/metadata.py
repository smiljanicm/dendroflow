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


def find_locations(
    *,
    site_id: int | None = None,
    initial_label: str | None = None,
) -> tuple[MetadataRow, ...]:
    """Find locations using site and/or their earliest label."""

    conditions: list[str] = []
    parameters: list[object] = []

    if site_id is not None:
        conditions.append("locations.site_id = %s")
        parameters.append(site_id)

    if initial_label is not None:
        conditions.append("initial_label.label = %s")
        parameters.append(initial_label)

    if not conditions:
        raise ValueError(
            "location lookup requires site_id or initial_label"
        )

    where_clause = " AND ".join(conditions)

    with connect("dendroflow_metadata") as connection:
        rows = connection.execute(
            f"""
            SELECT
                locations.location_id,
                locations.site_id,
                locations.location_type_id,
                locations.latitude,
                locations.longitude,
                locations.height_above_ground,
                locations.azimuth,
                initial_label.label,
                initial_label.valid_from,
                initial_label.valid_to
            FROM locations
            JOIN LATERAL (
                SELECT
                    location_labels.label,
                    location_labels.valid_from,
                    location_labels.valid_to
                FROM location_labels
                WHERE
                    location_labels.location_id = locations.location_id
                ORDER BY
                    location_labels.valid_from,
                    location_labels.location_label_id
                LIMIT 1
            ) AS initial_label ON TRUE
            WHERE {where_clause}
            ORDER BY locations.location_id
            """,
            tuple(parameters),
        ).fetchall()

    return tuple(
        MetadataRow(
            database_id=row[0],
            values={
                "site_id": row[1],
                "location_type_id": row[2],
                "latitude": row[3],
                "longitude": row[4],
                "height_above_ground": row[5],
                "azimuth": row[6],
                "initial_label": row[7],
                "initial_label_valid_from": row[8],
                "initial_label_valid_to": row[9],
            },
        )
        for row in rows
    )


def find_location_labels(
    location_id: int,
) -> tuple[MetadataRow, ...]:
    """Return the ordered label history for a location."""

    if location_id <= 0:
        raise ValueError(
            "location_id must be greater than zero"
        )

    with connect("dendroflow_metadata") as connection:
        rows = connection.execute(
            """
            SELECT
                location_label_id,
                location_id,
                label,
                valid_from,
                valid_to
            FROM location_labels
            WHERE location_id = %s
            ORDER BY
                valid_from,
                location_label_id
            """,
            (location_id,),
        ).fetchall()

    return tuple(
        MetadataRow(
            database_id=row[0],
            values={
                "location_id": row[1],
                "label": row[2],
                "valid_from": row[3],
                "valid_to": row[4],
            },
        )
        for row in rows
    )

