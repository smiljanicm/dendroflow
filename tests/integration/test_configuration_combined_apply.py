import os
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from psycopg import sql
from psycopg.errors import UniqueViolation

from dendroflow import database
from dendroflow.configuration.persistence import (
    ApplyError,
    ApplyErrorCode,
    ApplyExecutionError,
    ApplyStageStatus,
    ApplyStatus,
    apply_plan,
)
from dendroflow.configuration.persistence.transactions import (
    StageTransactionError,
)
from dendroflow.configuration.plan import (
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

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("DENDROFLOW_INTEGRATION") != "1",
        reason="Set DENDROFLOW_INTEGRATION=1 to run PostgreSQL integration tests",
    ),
]


# Ordered for deletion: dependants before referenced rows.
# Conditions are fixed test SQL; only the unique fixture tag is a parameter.
METADATA_TABLES = (
    (
        "deployment",
        "deployments",
        "deployment_id",
        (
            "variable_id IN "
            "(SELECT variable_id FROM variables WHERE variable = %s)"
        ),
    ),
    (
        "sensor",
        "sensors",
        "sensor_id",
        "serial_number = %s",
    ),
    (
        "sensor_model",
        "sensor_models",
        "sensor_model_id",
        "model = %s",
    ),
    (
        "sensor_type",
        "sensor_types",
        "sensor_type_id",
        "type = %s",
    ),
    (
        "variable",
        "variables",
        "variable_id",
        "variable = %s",
    ),
    (
        "location",
        "locations",
        "location_id",
        "site_id IN (SELECT site_id FROM sites WHERE site_code = %s)",
    ),
    (
        "location_type",
        "location_types",
        "location_type_id",
        "type = %s",
    ),
    (
        "site",
        "sites",
        "site_id",
        "site_code = %s",
    ),
)


def make_plan(tag, path):
    definitions = (
        (
            "site",
            ResolvedSiteValues(
                site_code=tag,
                name=tag,
            ),
        ),
        (
            "location_type",
            ResolvedLocationTypeValues(type=tag),
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
            ResolvedSensorTypeValues(type=tag),
        ),
        (
            "sensor_model",
            ResolvedSensorModelValues(
                model=tag,
                manufacturer="Combined apply integration test",
                sensor_type=PlannedRef("sensor_type", "sensor_type"),
            ),
        ),
        (
            "sensor",
            ResolvedSensorValues(
                serial_number=tag,
                sensor_model=PlannedRef("sensor_model", "sensor_model"),
            ),
        ),
        (
            "variable",
            ResolvedVariableValues(variable=tag),
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

    # Reverse source order to exercise dependency scheduling.
    metadata_items = tuple(
        ResolvedPlanItem(
            plan_id=resource_type,
            resource_type=resource_type,
            action=PlanAction.CREATE,
            values=values,
        )
        for resource_type, values in reversed(definitions)
    )
    file = ResolvedPlanItem(
        plan_id="file",
        resource_type="file",
        action=PlanAction.CREATE,
        values=ResolvedFileValues(
            filepath=str(path),
            timestamp_timezone="UTC",
            timestamp_format="%Y-%m-%d %H:%M:%S",
            reader_config={"reader": "csv", "options": {}},
        ),
    )
    interface = ResolvedPlanItem(
        plan_id="interface",
        resource_type="interface",
        action=PlanAction.CREATE,
        values=ResolvedInterfaceValues(
            file=PlannedRef("file", "file"),
            deployment=PlannedRef("deployment", "deployment"),
            values_column="value",
            timestamp_column="TIMESTAMP",
            unit="cm",
        ),
    )

    return ResolvedPlan(
        metadata_items=metadata_items,
        raw_items=(interface, file),
    )


def metadata_ids(connection, tag):
    found = {}

    for resource_type, table, primary_key, condition in METADATA_TABLES:
        rows = connection.execute(
            sql.SQL(
                "SELECT {} FROM {} WHERE {} ORDER BY {}"
            ).format(
                sql.Identifier(primary_key),
                sql.Identifier(table),
                sql.SQL(condition),
                sql.Identifier(primary_key),
            ),
            (tag,),
        ).fetchall()
        found[resource_type] = tuple(row[0] for row in rows)

    return found


def metadata_state(tag):
    with connect("dendroflow_metadata") as connection:
        return metadata_ids(connection, tag)


def raw_state(path):
    with connect("dendroflow_raw") as connection:
        files = connection.execute(
            """
            SELECT file_id
            FROM files
            WHERE filepath = %s
            ORDER BY file_id
            """,
            (str(path),),
        ).fetchall()

        interfaces = connection.execute(
            """
            SELECT interface_id, file_id, deployment_id, values_column
            FROM sensor_file_interfaces
            WHERE file_id IN (
                SELECT file_id
                FROM files
                WHERE filepath = %s
            )
            ORDER BY interface_id
            """,
            (str(path),),
        ).fetchall()

    return files, interfaces


@pytest.fixture
def combined_case(tmp_path):
    tag = f"combined_apply_{uuid4().hex}"
    path = tmp_path / f"{tag}.csv"
    plan = make_plan(tag, path)

    try:
        yield tag, path, plan
    finally:
        # Cleanup does not depend on apply returning generated IDs.
        with connect("dendroflow_raw") as connection:
            connection.execute(
                """
                DELETE FROM sensor_file_interfaces
                WHERE file_id IN (
                    SELECT file_id
                    FROM files
                    WHERE filepath = %s
                )
                """,
                (str(path),),
            )
            connection.execute(
                "DELETE FROM files WHERE filepath = %s",
                (str(path),),
            )

        with connect("dendroflow_metadata") as connection:
            ids = metadata_ids(connection, tag)

            for resource_type, table, primary_key, _ in METADATA_TABLES:
                if ids[resource_type]:
                    connection.execute(
                        sql.SQL(
                            "DELETE FROM {} WHERE {} = ANY(%s)"
                        ).format(
                            sql.Identifier(table),
                            sql.Identifier(primary_key),
                        ),
                        (list(ids[resource_type]),),
                    )


@pytest.fixture
def apply_connection_calls(monkeypatch):
    calls = []

    def tracked_connect(name):
        calls.append(name)
        return connect(name)

    # Record apply's connections while using the real database factory.
    # Fixture setup, inspection, and cleanup use the imported connect().
    monkeypatch.setattr(database, "connect", tracked_connect)
    return calls


def assert_no_rows(tag, path):
    assert all(not ids for ids in metadata_state(tag).values())
    assert raw_state(path) == ([], [])


def assert_database_cause(error, expected_type):
    stage_error = error.__cause__

    assert isinstance(stage_error, StageTransactionError)
    assert isinstance(stage_error.__cause__, expected_type)
    assert stage_error.rollback_error is None
    assert stage_error.close_error is None


def test_combined_apply_commits_both_stages(
    combined_case,
    apply_connection_calls,
):
    tag, path, plan = combined_case

    result = apply_plan(plan)

    assert result.status == ApplyStatus.SUCCESS
    assert result.metadata_status == ApplyStageStatus.COMMITTED
    assert result.raw_status == ApplyStageStatus.COMMITTED
    assert apply_connection_calls == [
        "dendroflow_metadata",
        "dendroflow_raw",
    ]
    assert [item.plan_id for item in result.items] == [
        item.plan_id for item in plan.items
    ]
    assert all(item.action == PlanAction.CREATE for item in result.items)

    ids = {
        item.plan_id: item.database_id
        for item in result.items
    }

    assert metadata_state(tag) == {
        item.resource_type: (ids[item.plan_id],)
        for item in plan.metadata_items
    }
    assert raw_state(path) == (
        [(ids["file"],)],
        [
            (
                ids["interface"],
                ids["file"],
                ids["deployment"],
                "value",
            ),
        ],
    )

    # Inspect the persisted deployment from another METADATA connection.
    with connect("dendroflow_metadata") as connection:
        deployment = connection.execute(
            """
            SELECT sensor_id, location_id, variable_id
            FROM deployments
            WHERE deployment_id = %s
            """,
            (ids["deployment"],),
        ).fetchone()

    assert deployment == (
        ids["sensor"],
        ids["location"],
        ids["variable"],
    )


def test_invalid_raw_preparation_prevents_all_writes(
    combined_case,
    apply_connection_calls,
):
    tag, path, plan = combined_case
    interface, file = plan.raw_items
    invalid_file = replace(
        file,
        values=replace(file.values, reader_config=[]),
    )
    plan = replace(
        plan,
        raw_items=(interface, invalid_file),
    )

    with pytest.raises(ApplyError) as caught:
        apply_plan(plan)

    assert caught.value.code == ApplyErrorCode.PLAN_NOT_APPLICABLE
    assert apply_connection_calls == []
    assert_no_rows(tag, path)


def test_metadata_failure_rolls_back_and_prevents_raw_stage(
    combined_case,
    apply_connection_calls,
):
    tag, path, plan = combined_case
    original_site = next(
        item
        for item in plan.metadata_items
        if item.resource_type == "site"
    )
    duplicate_site = replace(
        original_site,
        plan_id="duplicate-site",
    )
    plan = replace(
        plan,
        metadata_items=plan.metadata_items + (duplicate_site,),
    )

    with pytest.raises(ApplyExecutionError) as caught:
        apply_plan(plan)

    result = caught.value.result

    assert result.status == ApplyStatus.FAILED
    assert result.metadata_status == ApplyStageStatus.FAILED
    assert result.raw_status == ApplyStageStatus.NOT_STARTED
    assert result.items == ()
    assert apply_connection_calls == ["dendroflow_metadata"]
    assert_database_cause(caught.value, UniqueViolation)
    assert_no_rows(tag, path)


@pytest.mark.parametrize("duplicate_resource", ["file", "interface"])
def test_raw_failure_preserves_committed_metadata(
    combined_case,
    apply_connection_calls,
    duplicate_resource,
):
    tag, path, plan = combined_case
    interface, file = plan.raw_items

    duplicate = replace(
        file if duplicate_resource == "file" else interface,
        plan_id=f"duplicate-{duplicate_resource}",
    )
    plan = replace(
        plan,
        raw_items=plan.raw_items + (duplicate,),
    )

    with pytest.raises(ApplyExecutionError) as caught:
        apply_plan(plan)

    result = caught.value.result

    assert result.status == ApplyStatus.PARTIAL
    assert result.metadata_status == ApplyStageStatus.COMMITTED
    assert result.raw_status == ApplyStageStatus.FAILED
    assert apply_connection_calls == [
        "dendroflow_metadata",
        "dendroflow_raw",
    ]
    assert_database_cause(caught.value, UniqueViolation)

    # Only committed METADATA operations appear in the failure result.
    assert [item.plan_id for item in result.items] == [
        item.plan_id for item in plan.metadata_items
    ]

    ids = {
        item.resource_type: item.database_id
        for item in result.items
    }
    assert metadata_state(tag) == {
        resource_type: (database_id,)
        for resource_type, database_id in ids.items()
    }

    # Both the earlier file and interface INSERTs were rolled back.
    assert raw_state(path) == ([], [])

