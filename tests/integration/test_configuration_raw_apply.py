import os
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from psycopg import sql
from psycopg.errors import ForeignKeyViolation, UniqueViolation

from dendroflow.configuration.persistence import (
    ApplyStageStatus,
    ApplyStatus,
    apply_metadata_plan,
    apply_raw_plan,
)
from dendroflow.configuration.plan import (
    ExistingRef,
    PlanAction,
    PlannedRef,
    ResolvedDeploymentValues,
    ResolvedFileValues,
    ResolvedInterfaceValues,
    ResolvedLocationTypeValues,
    ResolvedLocationValues,
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSensorModelValues,
    ResolvedSensorTypeValues,
    ResolvedSensorValues,
    ResolvedSiteValues,
    ResolvedVariableValues,
)
from dendroflow.database import connect
from dendroflow.ingestion.sources import (
    get_source_file,
    get_source_interfaces,
    read_source_file,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("DENDROFLOW_INTEGRATION") != "1",
        reason="Set DENDROFLOW_INTEGRATION=1 to run PostgreSQL integration tests",
    ),
]


@pytest.fixture
def deployment_id():
    prefix = f"raw_apply_{uuid4().hex}"
    definitions = (
        (
            "site",
            ResolvedSiteValues(
                site_code=prefix,
                name=prefix,
            ),
        ),
        (
            "location_type",
            ResolvedLocationTypeValues(type=prefix),
        ),
        (
            "location",
            ResolvedLocationValues(
                site=PlannedRef("site", "site"),
                location_type=PlannedRef(
                    "location_type",
                    "location_type",
                ),
            ),
        ),
        (
            "sensor_type",
            ResolvedSensorTypeValues(type=prefix),
        ),
        (
            "sensor_model",
            ResolvedSensorModelValues(
                model=prefix,
                manufacturer="RAW apply integration test",
                sensor_type=PlannedRef("sensor_type", "sensor_type"),
            ),
        ),
        (
            "sensor",
            ResolvedSensorValues(
                serial_number=prefix,
                sensor_model=PlannedRef("sensor_model", "sensor_model"),
            ),
        ),
        (
            "variable",
            ResolvedVariableValues(variable=prefix),
        ),
        (
            "deployment",
            ResolvedDeploymentValues(
                sensor=PlannedRef("sensor", "sensor"),
                location=PlannedRef("location", "location"),
                variable=PlannedRef("variable", "variable"),
                valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                valid_to=None,
            ),
        ),
    )
    plan = ResolvedPlan(
        metadata_items=tuple(
            ResolvedPlanItem(
                plan_id=resource_type,
                resource_type=resource_type,
                action=PlanAction.CREATE,
                values=values,
            )
            for resource_type, values in definitions
        )
    )

    result = apply_metadata_plan(plan)
    ids = {
        item.resource_type: item.database_id
        for item in result.items
    }

    try:
        yield ids["deployment"]
    finally:
        cleanup = (
            ("deployments", "deployment_id", "deployment"),
            ("sensors", "sensor_id", "sensor"),
            ("sensor_models", "sensor_model_id", "sensor_model"),
            ("sensor_types", "sensor_type_id", "sensor_type"),
            ("variables", "variable_id", "variable"),
            ("locations", "location_id", "location"),
            ("location_types", "location_type_id", "location_type"),
            ("sites", "site_id", "site"),
        )

        with connect("dendroflow_metadata") as connection:
            for table, primary_key, resource_type in cleanup:
                connection.execute(
                    sql.SQL("DELETE FROM {} WHERE {} = %s").format(
                        sql.Identifier(table),
                        sql.Identifier(primary_key),
                    ),
                    (ids[resource_type],),
                )


@pytest.fixture
def raw_case(tmp_path, deployment_id):
    paths = tuple(
        tmp_path / f"source_{index}.csv"
        for index in range(3)
    )

    try:
        yield paths, deployment_id
    finally:
        # This fixture depends on deployment_id, so RAW cleanup runs first.
        with connect("dendroflow_raw") as connection:
            connection.execute(
                """
                DELETE FROM sensor_file_interfaces
                WHERE file_id IN (
                    SELECT file_id
                    FROM files
                    WHERE filepath = ANY(%s)
                )
                """,
                ([str(path) for path in paths],),
            )
            connection.execute(
                """
                DELETE FROM files
                WHERE filepath = ANY(%s)
                """,
                ([str(path) for path in paths],),
            )


def file_item(path, plan_id="file"):
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="file",
        action=PlanAction.CREATE,
        values=ResolvedFileValues(
            filepath=str(path),
            timestamp_timezone="UTC",
            timestamp_format="%Y-%m-%d %H:%M:%S",
            reader_config={
                "reader": "csv",
                "options": {
                    "sep": ";",
                    "dtype": {"value": "float64"},
                    "keep_default_na": False,
                },
            },
        ),
    )


def interface_item(
    deployment_id,
    *,
    plan_id="interface",
    file_ref=None,
    values_column="value",
):
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="interface",
        action=PlanAction.CREATE,
        values=ResolvedInterfaceValues(
            file=(
                PlannedRef("file", "file")
                if file_ref is None
                else file_ref
            ),
            deployment=ExistingRef("deployment", deployment_id),
            values_column=values_column,
            timestamp_column="TIMESTAMP",
            unit="cm",
        ),
    )


def result_ids(result):
    return {
        item.plan_id: item.database_id
        for item in result.items
    }


def raw_state(paths):
    parameters = ([str(path) for path in paths],)

    with connect("dendroflow_raw") as connection:
        files = connection.execute(
            """
            SELECT
                file_id,
                filepath,
                timestamp_timezone,
                timestamp_format,
                reader_config
            FROM files
            WHERE filepath = ANY(%s)
            ORDER BY file_id
            """,
            parameters,
        ).fetchall()

        interfaces = connection.execute(
            """
            SELECT
                interface_id,
                file_id,
                deployment_id,
                values_column,
                timestamp_column,
                unit
            FROM sensor_file_interfaces
            WHERE file_id IN (
                SELECT file_id
                FROM files
                WHERE filepath = ANY(%s)
            )
            ORDER BY interface_id
            """,
            parameters,
        ).fetchall()

    return files, interfaces


def test_raw_apply_commits_jsonb_and_supports_ingestion_readers(raw_case):
    paths, deployment_id = raw_case
    path = paths[0]
    file = file_item(path)
    interface = interface_item(deployment_id)

    assert not path.exists()

    # Reverse source order to exercise file-before-interface ordering.
    result = apply_raw_plan(
        ResolvedPlan(raw_items=(interface, file))
    )
    ids = result_ids(result)

    assert result.status == ApplyStatus.SUCCESS
    assert result.metadata_status == ApplyStageStatus.NOT_REQUIRED
    assert result.raw_status == ApplyStageStatus.COMMITTED
    assert [item.plan_id for item in result.items] == [
        "interface",
        "file",
    ]

    assert raw_state(paths) == (
        [
            (
                ids["file"],
                str(path),
                "UTC",
                "%Y-%m-%d %H:%M:%S",
                dict(file.values.reader_config),
            ),
        ],
        [
            (
                ids["interface"],
                ids["file"],
                deployment_id,
                "value",
                "TIMESTAMP",
                "cm",
            ),
        ],
    )

    source = get_source_file(ids["file"])
    assert source.filepath == path
    assert source.timestamp_timezone == "UTC"
    assert source.timestamp_format == "%Y-%m-%d %H:%M:%S"
    assert source.reader_config == file.values.reader_config

    interfaces = get_source_interfaces(ids["file"])
    assert len(interfaces) == 1
    assert interfaces[0].interface_id == ids["interface"]
    assert interfaces[0].file_id == ids["file"]
    assert interfaces[0].deployment_id == deployment_id
    assert interfaces[0].values_column == "value"
    assert interfaces[0].timestamp_column == "TIMESTAMP"
    assert interfaces[0].unit == "cm"

    # Registration does not require the physical file to exist.
    # Once present, ingestion can read it using the stored configuration.
    path.write_text(
        "TIMESTAMP;value\n"
        "2026-01-02 00:00:00;12.5\n",
        encoding="utf-8",
    )

    batches = list(read_source_file(ids["file"]))

    assert len(batches) == 1
    assert batches[0].source_line_numbers == (2,)
    assert batches[0].dataframe.to_dict("records") == [
        {
            "TIMESTAMP": "2026-01-02 00:00:00",
            "value": 12.5,
        },
    ]


def test_raw_apply_adds_interface_to_reused_file(raw_case):
    paths, deployment_id = raw_case
    file = file_item(paths[0])
    first = interface_item(deployment_id)

    initial = apply_raw_plan(
        ResolvedPlan(raw_items=(file, first))
    )
    ids = result_ids(initial)

    reused_file = replace(
        file,
        action=PlanAction.REUSE,
        database_id=ids["file"],
    )
    reused_interface = replace(
        first,
        action=PlanAction.REUSE,
        database_id=ids["interface"],
        values=replace(
            first.values,
            file=ExistingRef("file", ids["file"]),
        ),
    )
    second = interface_item(
        deployment_id,
        plan_id="second",
        file_ref=ExistingRef("file", ids["file"]),
        values_column="second_value",
    )

    result = apply_raw_plan(
        ResolvedPlan(
            raw_items=(second, reused_interface, reused_file),
        )
    )
    new_ids = result_ids(result)

    assert result.status == ApplyStatus.SUCCESS
    assert result.raw_status == ApplyStageStatus.COMMITTED
    assert [item.action for item in result.items] == [
        PlanAction.CREATE,
        PlanAction.REUSE,
        PlanAction.REUSE,
    ]
    assert new_ids["file"] == ids["file"]
    assert new_ids["interface"] == ids["interface"]

    files, interfaces = raw_state(paths)
    assert len(files) == 1
    assert interfaces == [
        (
            ids["interface"],
            ids["file"],
            deployment_id,
            "value",
            "TIMESTAMP",
            "cm",
        ),
        (
            new_ids["second"],
            ids["file"],
            deployment_id,
            "second_value",
            "TIMESTAMP",
            "cm",
        ),
    ]


def test_duplicate_filepath_rolls_back_earlier_file_and_interface(raw_case):
    paths, deployment_id = raw_case
    apply_raw_plan(
        ResolvedPlan(raw_items=(file_item(paths[1], "existing"),))
    )
    before = raw_state(paths)

    plan = ResolvedPlan(
        raw_items=(
            file_item(paths[0]),
            interface_item(deployment_id),
            file_item(paths[1], "duplicate"),
        )
    )

    with pytest.raises(UniqueViolation):
        apply_raw_plan(plan)

    assert raw_state(paths) == before


def test_duplicate_interface_rolls_back_entire_raw_plan(raw_case):
    paths, deployment_id = raw_case
    plan = ResolvedPlan(
        raw_items=(
            file_item(paths[0]),
            interface_item(deployment_id, plan_id="first"),
            interface_item(deployment_id, plan_id="duplicate"),
        )
    )

    # Both interfaces claim the same (file_id, values_column).
    with pytest.raises(UniqueViolation):
        apply_raw_plan(plan)

    assert raw_state(paths) == ([], [])


def test_missing_file_foreign_key_rolls_back_earlier_writes(raw_case):
    paths, deployment_id = raw_case

    # Obtain a real ID and remove its row, avoiding guessed database IDs.
    seeded = apply_raw_plan(
        ResolvedPlan(raw_items=(file_item(paths[2], "removed"),))
    )
    removed_id = result_ids(seeded)["removed"]

    with connect("dendroflow_raw") as connection:
        connection.execute(
            "DELETE FROM files WHERE file_id = %s",
            (removed_id,),
        )

    plan = ResolvedPlan(
        raw_items=(
            file_item(paths[0]),
            interface_item(deployment_id, plan_id="valid"),
            interface_item(
                deployment_id,
                plan_id="missing-file",
                file_ref=ExistingRef("file", removed_id),
            ),
        )
    )

    with pytest.raises(ForeignKeyViolation):
        apply_raw_plan(plan)

    assert raw_state(paths) == ([], [])
