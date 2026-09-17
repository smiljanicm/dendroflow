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
    ExistingRef,
    FieldChange,
    PlanAction,
    PlannedRef,
    ResolvedFileValues,
    ResolvedInterfaceValues,
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


@pytest.mark.parametrize("resource_type", ["site", "unknown"])
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

def interface_item():
    return ResolvedPlanItem(
        plan_id="files[0].interfaces[0]",
        resource_type="interface",
        action=PlanAction.CREATE,
        values=ResolvedInterfaceValues(
            file=ExistingRef("file", 17),
            deployment=ExistingRef("deployment", 91),
            values_column="water_level",
            timestamp_column="TIMESTAMP",
            unit="cm",
        ),
    )


@pytest.mark.parametrize("planned_file", [False, True])
@pytest.mark.parametrize("planned_deployment", [False, True])
def test_interface_create_resolves_references_and_registers_id(
    planned_file,
    planned_deployment,
):
    item = interface_item()
    context = ApplyContext()

    if planned_file:
        context.register(
            plan_id="files[0]",
            resource_type="file",
            database_id=17,
        )
        item = replace(
            item,
            values=replace(
                item.values,
                file=PlannedRef("file", "files[0]"),
            ),
        )

    if planned_deployment:
        context.register(
            plan_id="deployments[0]",
            resource_type="deployment",
            database_id=91,
        )
        item = replace(
            item,
            values=replace(
                item.values,
                deployment=PlannedRef("deployment", "deployments[0]"),
            ),
        )

    connection = FakeConnection(row=(101,))

    result = create_raw_item(connection, item, context)

    assert len(connection.calls) == 1
    assert connection.fetchone_calls == 1

    query, params = connection.calls[0]
    assert " ".join(query.split()) == (
        "INSERT INTO sensor_file_interfaces "
        "( file_id, deployment_id, values_column, timestamp_column, unit ) "
        "VALUES (%s, %s, %s, %s, %s) "
        "RETURNING interface_id"
    )
    assert params == (
        17,
        91,
        "water_level",
        "TIMESTAMP",
        "cm",
    )
    assert result == ApplyItemResult(
        plan_id=item.plan_id,
        resource_type="interface",
        action=PlanAction.CREATE,
        database_id=101,
    )
    assert context.resolve(
        PlannedRef("interface", item.plan_id)
    ) == 101


def test_interface_create_rejects_wrong_values_class_before_sql():
    item = replace(
        interface_item(),
        values=file_item().values,
    )
    connection = FakeConnection()
    context = ApplyContext()

    with pytest.raises(
        TypeError,
        match="interface CREATE requires ResolvedInterfaceValues",
    ):
        create_raw_item(connection, item, context)

    assert connection.calls == []
    assert_unregistered(context, item)


@pytest.mark.parametrize("field", ["file", "deployment"])
@pytest.mark.parametrize(
    ("reference", "error_type"),
    [
        (None, TypeError),
        (17, TypeError),
        (ExistingRef("site", 17), ValueError),
        (PlannedRef("site", "sites[0]"), ValueError),
    ],
    ids=[
        "missing-reference",
        "bare-id",
        "wrong-existing-type",
        "wrong-planned-type",
    ],
)
def test_interface_create_rejects_invalid_reference_before_sql(
    field,
    reference,
    error_type,
):
    item = interface_item()
    item = replace(
        item,
        values=replace(item.values, **{field: reference}),
    )
    connection = FakeConnection()
    context = ApplyContext()

    # A registered resource still cannot be used for the wrong relationship.
    context.register(
        plan_id="sites[0]",
        resource_type="site",
        database_id=17,
    )

    with pytest.raises(
        error_type,
        match=f"interface {field} requires",
    ):
        create_raw_item(connection, item, context)

    assert connection.calls == []
    assert_unregistered(context, item)


@pytest.mark.parametrize("field", ["file", "deployment"])
def test_interface_create_rejects_unresolved_planned_reference(field):
    item = interface_item()
    item = replace(
        item,
        values=replace(
            item.values,
            **{field: PlannedRef(field, "missing")},
        ),
    )
    connection = FakeConnection()
    context = ApplyContext()

    with pytest.raises(ApplyError) as caught:
        create_raw_item(connection, item, context)

    assert caught.value.code == ApplyErrorCode.UNRESOLVED_PLANNED_REF
    assert connection.calls == []
    assert_unregistered(context, item)


@pytest.mark.parametrize("field", ["file", "deployment"])
def test_interface_create_rejects_mismatched_registration(field):
    item = interface_item()
    item = replace(
        item,
        values=replace(
            item.values,
            **{field: PlannedRef(field, "registered")},
        ),
    )
    connection = FakeConnection()
    context = ApplyContext()
    context.register(
        plan_id="registered",
        resource_type="site",
        database_id=17,
    )

    with pytest.raises(ApplyError) as caught:
        create_raw_item(connection, item, context)

    assert caught.value.code == ApplyErrorCode.UNRESOLVED_PLANNED_REF
    assert connection.calls == []
    assert_unregistered(context, item)


def test_file_create_supplies_id_to_interface_create():
    connection = FakeConnection(row=(17,))
    context = ApplyContext()
    file = file_item()
    interface = interface_item()
    interface = replace(
        interface,
        values=replace(
            interface.values,
            file=PlannedRef("file", file.plan_id),
        ),
    )

    file_result = create_raw_item(connection, file, context)

    connection.row = (101,)
    interface_result = create_raw_item(connection, interface, context)

    assert file_result.database_id == 17
    assert interface_result.database_id == 101
    assert len(connection.calls) == 2
    assert connection.calls[1][1] == (
        17,
        91,
        "water_level",
        "TIMESTAMP",
        "cm",
    )
    assert context.resolve(
        PlannedRef("file", file.plan_id)
    ) == 17
    assert context.resolve(
        PlannedRef("interface", interface.plan_id)
    ) == 101


@pytest.mark.parametrize("failure_stage", ["execute", "fetchone"])
def test_interface_create_propagates_database_failure(failure_stage):
    failure = RuntimeError("interface database operation failed")
    item = interface_item()
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


@pytest.mark.parametrize(
    ("row", "error_type"),
    [
        (None, ValueError),
        ((True,), TypeError),
        ((0,), ValueError),
    ],
)
def test_interface_create_rejects_invalid_returned_id(row, error_type):
    item = interface_item()
    connection = FakeConnection(row=row)
    context = ApplyContext()

    with pytest.raises(error_type):
        create_raw_item(connection, item, context)

    assert len(connection.calls) == 1
    assert_unregistered(context, item)
