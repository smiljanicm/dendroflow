import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from dendroflow.database import connect
from dendroflow.ingestion import (
    create_ingestion_batch,
    create_ingestion_run_with_targets,
    fingerprint_file,
    get_deployments,
    get_or_create_file_version,
    get_source_file,
    get_source_interfaces,
    ingest_file,
    normalize_batch,
    read_source_file,
    start_ingestion_batch,
    write_ingestion_batch,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("DENDROFLOW_INTEGRATION") != "1",
        reason="Set DENDROFLOW_INTEGRATION=1 to run PostgreSQL integration tests",
    ),
]


@pytest.fixture
def raw_ingestion_fixture(tmp_path):
    suffix = uuid4().hex

    path = tmp_path / f"integration_{suffix}.csv"

    path.write_text(
        "TIMESTAMP,value_a,value_b\n"
        "2026-01-02 00:00:00,10.0,4.0\n"
        "2026-01-02 00:15:00,10.1,4.1\n"
        "2026-01-02 00:30:00,10.2,4.2\n"
        "2026-01-02 00:45:00,10.3,4.3\n"
        "2026-01-02 01:00:00,10.4,4.4\n"
        "2026-01-02 01:15:00,10.5,4.5\n"
    )

    metadata_ids = {}
    raw_ids = {}

    try:
        # -------------------------------------------------
        # METADATA fixture
        # -------------------------------------------------

        with connect("dendroflow_metadata") as connection:
            metadata_ids["site_id"] = connection.execute(
                """
                INSERT INTO sites (
                    name,
                    site_code
                )
                VALUES (%s, %s)
                RETURNING site_id
                """,
                (
                    f"Integration site {suffix}",
                    f"integration_{suffix}",
                ),
            ).fetchone()[0]

            metadata_ids["location_type_id"] = connection.execute(
                """
                INSERT INTO location_types (
                    type,
                    description
                )
                VALUES (%s, %s)
                RETURNING location_type_id
                """,
                (
                    f"integration_location_{suffix}",
                    "RAW integration test",
                ),
            ).fetchone()[0]

            metadata_ids["location_id"] = connection.execute(
                """
                INSERT INTO locations (
                    site_id,
                    location_type_id
                )
                VALUES (%s, %s)
                RETURNING location_id
                """,
                (
                    metadata_ids["site_id"],
                    metadata_ids["location_type_id"],
                ),
            ).fetchone()[0]

            metadata_ids["sensor_type_id"] = connection.execute(
                """
                INSERT INTO sensor_types (
                    type,
                    description
                )
                VALUES (%s, %s)
                RETURNING sensor_type_id
                """,
                (
                    f"integration_sensor_{suffix}",
                    "RAW integration test",
                ),
            ).fetchone()[0]

            metadata_ids["sensor_model_id"] = connection.execute(
                """
                INSERT INTO sensor_models (
                    model,
                    manufacturer,
                    sensor_type_id
                )
                VALUES (%s, %s, %s)
                RETURNING sensor_model_id
                """,
                (
                    f"model_{suffix}",
                    "DendroFlow integration test",
                    metadata_ids["sensor_type_id"],
                ),
            ).fetchone()[0]

            metadata_ids["sensor_id"] = connection.execute(
                """
                INSERT INTO sensors (
                    sensor_model_id,
                    serial_number,
                    description
                )
                VALUES (%s, %s, %s)
                RETURNING sensor_id
                """,
                (
                    metadata_ids["sensor_model_id"],
                    f"serial_{suffix}",
                    "RAW integration test",
                ),
            ).fetchone()[0]

            metadata_ids["variable_a_id"] = connection.execute(
                """
                INSERT INTO variables (
                    variable,
                    description
                )
                VALUES (%s, %s)
                RETURNING variable_id
                """,
                (
                    f"integration_a_{suffix}",
                    "RAW integration test variable A",
                ),
            ).fetchone()[0]

            metadata_ids["variable_b_id"] = connection.execute(
                """
                INSERT INTO variables (
                    variable,
                    description
                )
                VALUES (%s, %s)
                RETURNING variable_id
                """,
                (
                    f"integration_b_{suffix}",
                    "RAW integration test variable B",
                ),
            ).fetchone()[0]

            valid_from = datetime(
                2026,
                1,
                1,
                tzinfo=timezone.utc,
            )

            metadata_ids["deployment_a_id"] = connection.execute(
                """
                INSERT INTO deployments (
                    sensor_id,
                    location_id,
                    variable_id,
                    valid_from
                )
                VALUES (%s, %s, %s, %s)
                RETURNING deployment_id
                """,
                (
                    metadata_ids["sensor_id"],
                    metadata_ids["location_id"],
                    metadata_ids["variable_a_id"],
                    valid_from,
                ),
            ).fetchone()[0]

            metadata_ids["deployment_b_id"] = connection.execute(
                """
                INSERT INTO deployments (
                    sensor_id,
                    location_id,
                    variable_id,
                    valid_from
                )
                VALUES (%s, %s, %s, %s)
                RETURNING deployment_id
                """,
                (
                    metadata_ids["sensor_id"],
                    metadata_ids["location_id"],
                    metadata_ids["variable_b_id"],
                    valid_from,
                ),
            ).fetchone()[0]

        # -------------------------------------------------
        # RAW fixture
        # -------------------------------------------------

        with connect("dendroflow_raw") as connection:
            raw_ids["file_id"] = connection.execute(
                """
                INSERT INTO files (
                    filepath,
                    timestamp_timezone,
                    timestamp_format,
                    reader_config
                )
                VALUES (%s, %s, %s, %s)
                RETURNING file_id
                """,
                (
                    str(path),
                    "UTC",
                    "%Y-%m-%d %H:%M:%S",
                    Jsonb(
                        {
                            "reader": "csv",
                            "options": {
                                "chunksize": 2,
                            },
                        }
                    ),
                ),
            ).fetchone()[0]

            interface_a = connection.execute(
                """
                INSERT INTO sensor_file_interfaces (
                    file_id,
                    deployment_id,
                    values_column,
                    timestamp_column,
                    unit
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING interface_id
                """,
                (
                    raw_ids["file_id"],
                    metadata_ids["deployment_a_id"],
                    "value_a",
                    "TIMESTAMP",
                    "unit_a",
                ),
            ).fetchone()[0]

            interface_b = connection.execute(
                """
                INSERT INTO sensor_file_interfaces (
                    file_id,
                    deployment_id,
                    values_column,
                    timestamp_column,
                    unit
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING interface_id
                """,
                (
                    raw_ids["file_id"],
                    metadata_ids["deployment_b_id"],
                    "value_b",
                    "TIMESTAMP",
                    "unit_b",
                ),
            ).fetchone()[0]

            raw_ids["interface_ids"] = (
                interface_a,
                interface_b,
            )

        yield {
            "file_id": raw_ids["file_id"],
            "path": path,
        }

    finally:
        # -------------------------------------------------
        # RAW cleanup
        # -------------------------------------------------

        if "file_id" in raw_ids:
            file_id = raw_ids["file_id"]

            with connect("dendroflow_raw") as connection:
                run_rows = connection.execute(
                    """
                    SELECT DISTINCT ingestion_run_id
                    FROM ingestion_targets
                    WHERE file_version_id IN (
                        SELECT file_version_id
                        FROM file_versions
                        WHERE file_id = %s
                    )
                    """,
                    (file_id,),
                ).fetchall()

                run_ids = [
                    row[0]
                    for row in run_rows
                ]

                if run_ids:
                    connection.execute(
                        """
                        DELETE FROM ingestion_interfaces
                        WHERE ingestion_run_id = ANY(%s)
                        """,
                        (run_ids,),
                    )

                    connection.execute(
                        """
                        DELETE FROM raw_observations
                        WHERE ingestion_run_id = ANY(%s)
                        """,
                        (run_ids,),
                    )

                    connection.execute(
                        """
                        DELETE FROM ingestion_batches
                        WHERE ingestion_run_id = ANY(%s)
                        """,
                        (run_ids,),
                    )

                    connection.execute(
                        """
                        DELETE FROM ingestion_targets
                        WHERE ingestion_run_id = ANY(%s)
                        """,
                        (run_ids,),
                    )

                    connection.execute(
                        """
                        DELETE FROM ingestion_runs
                        WHERE ingestion_run_id = ANY(%s)
                        """,
                        (run_ids,),
                    )

                connection.execute(
                    """
                    DELETE FROM sensor_file_interfaces
                    WHERE file_id = %s
                    """,
                    (file_id,),
                )

                connection.execute(
                    """
                    DELETE FROM file_versions
                    WHERE file_id = %s
                    """,
                    (file_id,),
                )

                connection.execute(
                    """
                    DELETE FROM files
                    WHERE file_id = %s
                    """,
                    (file_id,),
                )

        # -------------------------------------------------
        # METADATA cleanup
        # -------------------------------------------------

        if metadata_ids:
            with connect("dendroflow_metadata") as connection:
                deployment_ids = [
                    deployment_id
                    for key, deployment_id in metadata_ids.items()
                    if key.startswith("deployment_")
                ]

                if deployment_ids:
                    connection.execute(
                        """
                        DELETE FROM deployments
                        WHERE deployment_id = ANY(%s)
                        """,
                        (deployment_ids,),
                    )

                if "sensor_id" in metadata_ids:
                    connection.execute(
                        """
                        DELETE FROM sensors
                        WHERE sensor_id = %s
                        """,
                        (metadata_ids["sensor_id"],),
                    )

                variable_ids = [
                    metadata_ids[key]
                    for key in (
                        "variable_a_id",
                        "variable_b_id",
                    )
                    if key in metadata_ids
                ]

                if variable_ids:
                    connection.execute(
                        """
                        DELETE FROM variables
                        WHERE variable_id = ANY(%s)
                        """,
                        (variable_ids,),
                    )

                if "location_id" in metadata_ids:
                    connection.execute(
                        """
                        DELETE FROM locations
                        WHERE location_id = %s
                        """,
                        (metadata_ids["location_id"],),
                    )

                if "sensor_model_id" in metadata_ids:
                    connection.execute(
                        """
                        DELETE FROM sensor_models
                        WHERE sensor_model_id = %s
                        """,
                        (metadata_ids["sensor_model_id"],),
                    )

                if "sensor_type_id" in metadata_ids:
                    connection.execute(
                        """
                        DELETE FROM sensor_types
                        WHERE sensor_type_id = %s
                        """,
                        (metadata_ids["sensor_type_id"],),
                    )

                if "location_type_id" in metadata_ids:
                    connection.execute(
                        """
                        DELETE FROM location_types
                        WHERE location_type_id = %s
                        """,
                        (metadata_ids["location_type_id"],),
                    )

                if "site_id" in metadata_ids:
                    connection.execute(
                        """
                        DELETE FROM sites
                        WHERE site_id = %s
                        """,
                        (metadata_ids["site_id"],),
                    )


def test_raw_ingestion_resumes_interrupted_run(
    raw_ingestion_fixture,
):
    file_id = raw_ingestion_fixture["file_id"]

    source_file = get_source_file(file_id)

    fingerprint = fingerprint_file(
        source_file.filepath
    )

    file_version = get_or_create_file_version(
        file_id,
        fingerprint,
    )

    interfaces = get_source_interfaces(file_id)

    deployments = get_deployments(
        tuple(
            interface.deployment_id
            for interface in interfaces
        )
    )

    run = create_ingestion_run_with_targets(
        file_version.file_version_id,
        interfaces,
    )

    reader = iter(
        read_source_file(file_id)
    )

    # ---------------------------------------
    # Batch 1 completes successfully
    # ---------------------------------------

    tabular_batch_1 = next(reader)

    batch_1 = create_ingestion_batch(
        ingestion_run_id=run.ingestion_run_id,
        file_version_id=file_version.file_version_id,
        batch_number=1,
        source_line_start=tabular_batch_1.source_line_numbers[0],
        source_line_end=tabular_batch_1.source_line_numbers[-1],
        row_count=len(tabular_batch_1.dataframe),
    )

    batch_1 = start_ingestion_batch(
        batch_1.ingestion_batch_id
    )

    observations = normalize_batch(
        tabular_batch_1,
        source_file,
        interfaces,
        deployments,
    )

    write_ingestion_batch(
        batch_1,
        observations,
    )

    # ---------------------------------------
    # Batch 2 starts, then process "crashes"
    # ---------------------------------------

    tabular_batch_2 = next(reader)

    batch_2 = create_ingestion_batch(
        ingestion_run_id=run.ingestion_run_id,
        file_version_id=file_version.file_version_id,
        batch_number=2,
        source_line_start=tabular_batch_2.source_line_numbers[0],
        source_line_end=tabular_batch_2.source_line_numbers[-1],
        row_count=len(tabular_batch_2.dataframe),
    )

    start_ingestion_batch(
        batch_2.ingestion_batch_id
    )

    # ---------------------------------------
    # Normal public API resumes the run
    # ---------------------------------------

    resumed_run = ingest_file(file_id)

    assert resumed_run.ingestion_run_id == run.ingestion_run_id
    assert resumed_run.status == "completed"

    # ---------------------------------------
    # Verify actual PostgreSQL state
    # ---------------------------------------

    with connect("dendroflow_raw") as connection:
        batches = connection.execute(
            """
            SELECT
                batch_number,
                source_line_start,
                source_line_end,
                row_count,
                status,
                attempt_count
            FROM ingestion_batches
            WHERE ingestion_run_id = %s
            ORDER BY batch_number
            """,
            (run.ingestion_run_id,),
        ).fetchall()

        observation_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM raw_observations
            WHERE ingestion_run_id = %s
            """,
            (run.ingestion_run_id,),
        ).fetchone()[0]

        interface_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM ingestion_interfaces
            WHERE ingestion_run_id = %s
            """,
            (run.ingestion_run_id,),
        ).fetchone()[0]

        target_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM ingestion_targets
            WHERE ingestion_run_id = %s
            """,
            (run.ingestion_run_id,),
        ).fetchone()[0]

    assert batches == [
        (1, 2, 3, 2, "completed", 1),
        (2, 4, 5, 2, "completed", 2),
        (3, 6, 7, 2, "completed", 1),
    ]

    assert observation_count == 12
    assert interface_count == 2
    assert target_count == 2
