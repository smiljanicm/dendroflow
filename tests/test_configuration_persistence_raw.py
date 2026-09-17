import json
from dataclasses import replace
from types import MappingProxyType

import pytest
from psycopg.types.json import Jsonb

from dendroflow.configuration.persistence.context import ApplyContext
from dendroflow.configuration.persistence.models import (
    ApplyError,
    ApplyErrorCode,
    ApplyItemResult,
)
from dendroflow.configuration.persistence.raw import create_raw_item
from dendroflow.configuration.plan import (
    FieldChange,
    PlanAction,
    PlannedRef,
    ResolvedFileValues,
    ResolvedPlanItem,
    ResolvedSiteValues,
)


class FakeConnection:
    def __init__(
        self,
        row=(17,),
        *,
        failure=None,
        failure_stage=None,
    ):
        self.row = row
        self.failure = failure
        self.failure_stage = failure_stage
        self.calls = []
        self.fetchone_calls = 0

    def execute(self, query, params):
        self.calls.append((query, params))

        if self.failure_stage == "execute":
            raise self.failure

        return self

    def fetchone(self):
        self.fetchone_calls += 1

        if self.failure_stage == "fetchone":
            raise self.failure

        return self.row


def file_item():
    return ResolvedPlanItem(
        plan_id="files[0]",
        resource_type="file",
        action=PlanAction.CREATE,
        values=ResolvedFileValues(
            filepath="../backups/O'Brien station.csv",
            timestamp_timezone="Europe/Berlin",
            timestamp_format="%Y-%m-%d %H:%M:%S",
            reader_config={
                "reader": "csv",
                "options": {"sep": ";"},
            },
        ),
    )


def assert_unregistered(context, item):
    with pytest.raises(ApplyError) as caught:
        context.resolve(
            PlannedRef(
                resource_type=item.resource_type,
                plan_id=item.plan_id,
            )
        )

    assert caught.value.code == ApplyErrorCode.UNRESOLVED_PLANNED_REF


@pytest.mark.parametrize(
    "reader_config",
    [
        {},
        {
            "reader": "csv",
            "options": {
                "sep": ";",
                "skiprows": [0, 1],
                "header": None,
                "keep_default_na": False,
                "dtype": {"value": "float64"},
            },
        },
        MappingProxyType(
            {
                "reader": "csv",
                "options": {"sep": ","},
            }
        ),
    ],
    ids=["empty", "nested-options", "readonly-mapping"],
)
def test_file_create_persists_values_and_registers_id(reader_config):
    item = file_item()
    item = replace(
        item,
        values=replace(
            item.values,
            reader_config=reader_config,
        ),
    )
    original_json = json.dumps(dict(reader_config), sort_keys=True)
    connection = FakeConnection()
    context = ApplyContext()

    result = create_raw_item(connection, item, context)

    assert len(connection.calls) == 1
    assert connection.fetchone_calls == 1

    query, params = connection.calls[0]
    assert " ".join(query.split()) == (
        "INSERT INTO files "
        "( filepath, timestamp_timezone, timestamp_format, reader_config ) "
        "VALUES (%s, %s, %s, %s) "
        "RETURNING file_id"
    )
    assert params[:3] == (
        "../backups/O'Brien station.csv",
        "Europe/Berlin",
        "%Y-%m-%d %H:%M:%S",
    )
    assert len(params) == 4
    assert isinstance(params[3], Jsonb)
    assert isinstance(params[3].obj, dict)
    assert params[3].obj is not reader_config
    assert json.dumps(params[3].obj, sort_keys=True) == original_json
    assert json.dumps(dict(reader_config), sort_keys=True) == original_json

    assert result == ApplyItemResult(
        plan_id="files[0]",
        resource_type="file",
        action=PlanAction.CREATE,
        database_id=17,
    )
    assert context.resolve(PlannedRef("file", "files[0]")) == 17


@pytest.mark.parametrize(
    "action",
    [PlanAction.REUSE, PlanAction.UPDATE],
)
def test_raw_create_rejects_non_create_action_before_sql(action):
    changes = ()

    if action == PlanAction.UPDATE:
        changes = (
            FieldChange(
                field="timestamp_timezone",
                before="UTC",
                after="Europe/Berlin",
            ),
        )

    item = replace(
        file_item(),
        action=action,
        database_id=17,
        changes=changes,
    )
    connection = FakeConnection()
    context = ApplyContext()

    with pytest.raises(ValueError, match="requires CREATE action"):
        create_raw_item(connection, item, context)

    assert connection.calls == []
    assert_unregistered(context, item)


@pytest.mark.parametrize("resource_type", ["site", "interface"])
def test_raw_create_rejects_unsupported_resource_before_sql(resource_type):
    item = replace(file_item(), resource_type=resource_type)
    connection = FakeConnection()
    context = ApplyContext()

    with pytest.raises(
        ValueError,
        match="unsupported RAW CREATE resource type",
    ):
        create_raw_item(connection, item, context)

    assert connection.calls == []
    assert_unregistered(context, item)


def test_file_create_rejects_wrong_values_class_before_sql():
    item = replace(
        file_item(),
        values=ResolvedSiteValues(
            site_code="TEST",
            name="Test site",
        ),
    )
    connection = FakeConnection()
    context = ApplyContext()

    with pytest.raises(
        TypeError,
        match="file CREATE requires ResolvedFileValues",
    ):
        create_raw_item(connection, item, context)

    assert connection.calls == []
    assert_unregistered(context, item)


@pytest.mark.parametrize("reader_config", [None, [], "csv"])
def test_file_create_rejects_non_mapping_reader_config_before_sql(
    reader_config,
):
    item = file_item()
    item = replace(
        item,
        values=replace(
            item.values,
            reader_config=reader_config,
        ),
    )
    connection = FakeConnection()
    context = ApplyContext()

    with pytest.raises(
        TypeError,
        match="reader_config must be a mapping",
    ):
        create_raw_item(connection, item, context)

    assert connection.calls == []
    assert_unregistered(context, item)


@pytest.mark.parametrize(
    ("row", "error_type"),
    [
        (None, ValueError),
        ((), ValueError),
        ((17, 18), ValueError),
        ((0,), ValueError),
        ((-1,), ValueError),
        ((True,), TypeError),
        (("17",), TypeError),
        ((17.0,), TypeError),
    ],
    ids=[
        "missing-row",
        "empty-row",
        "extra-column",
        "zero-id",
        "negative-id",
        "boolean-id",
        "string-id",
        "float-id",
    ],
)
def test_file_create_rejects_invalid_returned_id(row, error_type):
    item = file_item()
    connection = FakeConnection(row=row)
    context = ApplyContext()

    with pytest.raises(error_type):
        create_raw_item(connection, item, context)

    assert len(connection.calls) == 1
    assert connection.fetchone_calls == 1
    assert_unregistered(context, item)


@pytest.mark.parametrize("failure_stage", ["execute", "fetchone"])
def test_file_create_propagates_database_failure(failure_stage):
    failure = RuntimeError("database operation failed")
    item = file_item()
    connection = FakeConnection(
        failure=failure,
        failure_stage=failure_stage,
    )
    context = ApplyContext()

    with pytest.raises(RuntimeError) as caught:
        create_raw_item(connection, item, context)

    assert caught.value is failure
    assert len(connection.calls) == 1
    assert connection.fetchone_calls == (
        0 if failure_stage == "execute" else 1
    )
    assert_unregistered(context, item)


def test_file_create_does_not_overwrite_existing_registration():
    item = file_item()
    connection = FakeConnection(row=(18,))
    context = ApplyContext()
    context.register(
        plan_id=item.plan_id,
        resource_type="file",
        database_id=17,
    )

    with pytest.raises(ValueError, match="plan_id already registered"):
        create_raw_item(connection, item, context)

    assert context.resolve(
        PlannedRef("file", item.plan_id)
    ) == 17
