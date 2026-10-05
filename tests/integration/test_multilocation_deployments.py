"""Exercise the migrated database rule for a multi-depth physical sensor."""

import os
from uuid import uuid4

import pytest
from psycopg.errors import ExclusionViolation

from dendroflow.database import connect

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("DENDROFLOW_INTEGRATION") != "1",
        reason="Set DENDROFLOW_INTEGRATION=1 to run PostgreSQL integration tests",
    ),
]


def test_one_sensor_measures_same_variable_at_two_depths():
    tag = f"multidepth_{uuid4().hex}"

    with connect("dendroflow_metadata") as connection:
        try:
            site_id = connection.execute(
                "INSERT INTO sites (site_code, name) VALUES (%s, %s) "
                "RETURNING site_id",
                (tag, tag),
            ).fetchone()[0]
            location_type_id = connection.execute(
                "INSERT INTO location_types (type) VALUES (%s) "
                "RETURNING location_type_id",
                (tag,),
            ).fetchone()[0]
            locations = [
                connection.execute(
                    "INSERT INTO locations (site_id, location_type_id, "
                    "height_above_ground) VALUES (%s, %s, %s) "
                    "RETURNING location_id",
                    (site_id, location_type_id, depth),
                ).fetchone()[0]
                for depth in (-0.05, -0.10)
            ]
            sensor_type_id = connection.execute(
                "INSERT INTO sensor_types (type) VALUES (%s) "
                "RETURNING sensor_type_id",
                (tag,),
            ).fetchone()[0]
            sensor_model_id = connection.execute(
                "INSERT INTO sensor_models (model, manufacturer, sensor_type_id) "
                "VALUES (%s, %s, %s) RETURNING sensor_model_id",
                (tag, tag, sensor_type_id),
            ).fetchone()[0]
            sensor_id = connection.execute(
                "INSERT INTO sensors (sensor_model_id, serial_number) "
                "VALUES (%s, %s) RETURNING sensor_id",
                (sensor_model_id, tag),
            ).fetchone()[0]
            variable_id = connection.execute(
                "INSERT INTO variables (variable) VALUES (%s) "
                "RETURNING variable_id",
                (tag,),
            ).fetchone()[0]

            for location_id in locations:
                connection.execute(
                    "INSERT INTO deployments "
                    "(sensor_id, location_id, variable_id, valid_from) "
                    "VALUES (%s, %s, %s, %s)",
                    (sensor_id, location_id, variable_id, "2024-01-01T00:00:00Z"),
                )

            with pytest.raises(ExclusionViolation), connection.transaction():
                connection.execute(
                    "INSERT INTO deployments "
                    "(sensor_id, location_id, variable_id, valid_from) "
                    "VALUES (%s, %s, %s, %s)",
                    (
                        sensor_id,
                        locations[0],
                        variable_id,
                        "2024-06-01T00:00:00Z",
                    ),
                )

            assert connection.execute(
                "SELECT count(*) FROM deployments WHERE sensor_id = %s",
                (sensor_id,),
            ).fetchone()[0] == 2
        finally:
            # This integration test leaves no metadata behind.
            connection.rollback()
