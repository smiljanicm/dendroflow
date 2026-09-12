import pytest

from dendroflow.configuration.persistence.context import (
    ApplyContext,
)
from dendroflow.configuration.persistence.metadata import (
    create_metadata_item,
)
from dendroflow.configuration.persistence.models import (
    ApplyError,
    ApplyErrorCode,
    ApplyItemResult,
)
from dendroflow.configuration.plan import (
    FieldChange,
    PlanAction,
    PlannedRef,
    ResolvedLocationTypeValues,
    ResolvedPlanItem,
    ResolvedSensorTypeValues,
    ResolvedSiteValues,
    ResolvedVariableValues,
)

_METADATA_RESOURCE_TYPES = {
    "site",
    "location_type",
    "sensor_type",
    "variable",
    "sensor_model",
    "sensor",
    "location",
    "location_label",
    "deployment",
}


class FailIfUsedConnection:
    def execute(self, *args, **kwargs):
        raise AssertionError(
            "database must not be accessed"
        )


def test_metadata_create_rejects_reuse_action():
    item = ResolvedPlanItem(
        plan_id="sites[0]",
        resource_type="site",
        action=PlanAction.REUSE,
        database_id=17,
        values=ResolvedSiteValues(
            site_code="TEST",
            name="Test site",
        ),
    )

    context = ApplyContext()

    with pytest.raises(
        ValueError,
        match="requires CREATE action",
    ):
        create_metadata_item(
            FailIfUsedConnection(),
            item,
            context,
        )


def test_metadata_create_rejects_update_action():
    item = ResolvedPlanItem(
        plan_id="updates.sites[0]",
        resource_type="site",
        action=PlanAction.UPDATE,
        database_id=17,
        values=ResolvedSiteValues(
            site_code="TEST",
            name="Updated site",
        ),
        changes=(
            FieldChange(
                field="name",
                before="Old site",
                after="Updated site",
            ),
        ),
    )

    context = ApplyContext()

    with pytest.raises(
        ValueError,
        match="requires CREATE action",
    ):
        create_metadata_item(
            FailIfUsedConnection(),
            item,
            context,
        )


def test_metadata_create_rejects_non_metadata_resource():
    item = ResolvedPlanItem(
        plan_id="files[0]",
        resource_type="file",
        action=PlanAction.CREATE,
        values=object(),
    )

    context = ApplyContext()

    with pytest.raises(
        ValueError,
        match="unsupported METADATA resource type",
    ):
        create_metadata_item(
            FailIfUsedConnection(),
            item,
            context,
        )


def test_metadata_create_rejects_unknown_resource():
    item = ResolvedPlanItem(
        plan_id="unknown[0]",
        resource_type="something_else",
        action=PlanAction.CREATE,
        values=object(),
    )

    context = ApplyContext()

    with pytest.raises(
        ValueError,
        match="unsupported METADATA resource type",
    ):
        create_metadata_item(
            FailIfUsedConnection(),
            item,
            context,
        )


class FakeConnection:
    def __init__(self, returned_id=17):
        self.returned_id = returned_id
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))
        return self

    def fetchone(self):
        return (self.returned_id,)


def test_metadata_create_persists_site():
    connection = FakeConnection(returned_id=17)
    context = ApplyContext()

    item = ResolvedPlanItem(
        plan_id="sites[0]",
        resource_type="site",
        action=PlanAction.CREATE,
        values=ResolvedSiteValues(
            site_code="SAN",
            name="Sandhagen",
        ),
    )

    result = create_metadata_item(
        connection,
        item,
        context,
    )

    assert result == ApplyItemResult(
        plan_id="sites[0]",
        resource_type="site",
        action=PlanAction.CREATE,
        database_id=17,
    )

    assert context.resolve(
        PlannedRef(
            resource_type="site",
            plan_id="sites[0]",
        )
    ) == 17


def test_metadata_create_site_uses_resolved_values():
    connection = FakeConnection(returned_id=17)
    context = ApplyContext()

    item = ResolvedPlanItem(
        plan_id="sites[0]",
        resource_type="site",
        action=PlanAction.CREATE,
        values=ResolvedSiteValues(
            site_code="SAN",
            name="Sandhagen",
        ),
    )

    create_metadata_item(
        connection,
        item,
        context,
    )

    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert "INSERT INTO sites" in query
    assert "RETURNING site_id" in query
    assert params == ("Sandhagen", "SAN")


@pytest.mark.parametrize("returned_id", [0, -1])
def test_metadata_create_site_rejects_invalid_returned_id(
    returned_id,
):
    connection = FakeConnection(returned_id=returned_id)
    context = ApplyContext()

    item = ResolvedPlanItem(
        plan_id="sites[0]",
        resource_type="site",
        action=PlanAction.CREATE,
        values=ResolvedSiteValues(
            site_code="SAN",
            name="Sandhagen",
        ),
    )

    with pytest.raises(
        ValueError,
        match="database_id must be positive",
    ):
        create_metadata_item(
            connection,
            item,
            context,
        )


class FailingConnection:
    def execute(self, query, params):
        raise RuntimeError("database failure")


def test_metadata_create_site_does_not_register_on_database_failure():
    context = ApplyContext()

    item = ResolvedPlanItem(
        plan_id="sites[0]",
        resource_type="site",
        action=PlanAction.CREATE,
        values=ResolvedSiteValues(
            site_code="SAN",
            name="Sandhagen",
        ),
    )

    with pytest.raises(RuntimeError, match="database failure"):
        create_metadata_item(
            FailingConnection(),
            item,
            context,
        )

    with pytest.raises(ApplyError) as exc_info:
        context.resolve(
            PlannedRef(
                resource_type="site",
                plan_id="sites[0]",
            )
        )

    assert (
        exc_info.value.code
        == ApplyErrorCode.UNRESOLVED_PLANNED_REF
    )


def test_metadata_create_persists_location_type():
    connection = FakeConnection(returned_id=21)
    context = ApplyContext()

    item = ResolvedPlanItem(
        plan_id="location_types[0]",
        resource_type="location_type",
        action=PlanAction.CREATE,
        values=ResolvedLocationTypeValues(
            type="plot",
            description="Monitoring plot",
        ),
    )

    result = create_metadata_item(
        connection,
        item,
        context,
    )

    assert result == ApplyItemResult(
        plan_id="location_types[0]",
        resource_type="location_type",
        action=PlanAction.CREATE,
        database_id=21,
    )

    assert context.resolve(
        PlannedRef(
            resource_type="location_type",
            plan_id="location_types[0]",
        )
    ) == 21


def test_metadata_create_location_type_uses_resolved_values():
    connection = FakeConnection(returned_id=21)
    context = ApplyContext()

    item = ResolvedPlanItem(
        plan_id="location_types[0]",
        resource_type="location_type",
        action=PlanAction.CREATE,
        values=ResolvedLocationTypeValues(
            type="plot",
            description="Monitoring plot",
        ),
    )

    create_metadata_item(
        connection,
        item,
        context,
    )

    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert "INSERT INTO location_types" in query
    assert "RETURNING location_type_id" in query
    assert params == (
        "plot",
        "Monitoring plot",
    )


def test_metadata_create_persists_sensor_type():
    connection = FakeConnection(returned_id=31)
    context = ApplyContext()

    item = ResolvedPlanItem(
        plan_id="sensor_types[0]",
        resource_type="sensor_type",
        action=PlanAction.CREATE,
        values=ResolvedSensorTypeValues(
            type="pressure transducer",
            description="Water-level pressure sensor",
        ),
    )

    result = create_metadata_item(
        connection,
        item,
        context,
    )

    assert result == ApplyItemResult(
        plan_id="sensor_types[0]",
        resource_type="sensor_type",
        action=PlanAction.CREATE,
        database_id=31,
    )

    assert context.resolve(
        PlannedRef(
            resource_type="sensor_type",
            plan_id="sensor_types[0]",
        )
    ) == 31


def test_metadata_create_sensor_type_uses_resolved_values():
    connection = FakeConnection(returned_id=31)
    context = ApplyContext()

    item = ResolvedPlanItem(
        plan_id="sensor_types[0]",
        resource_type="sensor_type",
        action=PlanAction.CREATE,
        values=ResolvedSensorTypeValues(
            type="pressure transducer",
            description="Water-level pressure sensor",
        ),
    )

    create_metadata_item(
        connection,
        item,
        context,
    )

    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert "INSERT INTO sensor_types" in query
    assert "RETURNING sensor_type_id" in query
    assert params == (
        "pressure transducer",
        "Water-level pressure sensor",
    )


def test_metadata_create_persists_variable():
    connection = FakeConnection(returned_id=41)
    context = ApplyContext()

    item = ResolvedPlanItem(
        plan_id="variables[0]",
        resource_type="variable",
        action=PlanAction.CREATE,
        values=ResolvedVariableValues(
            variable="water_level",
            derived=False,
            description="Water-table level",
        ),
    )

    result = create_metadata_item(
        connection,
        item,
        context,
    )

    assert result == ApplyItemResult(
        plan_id="variables[0]",
        resource_type="variable",
        action=PlanAction.CREATE,
        database_id=41,
    )

    assert context.resolve(
        PlannedRef(
            resource_type="variable",
            plan_id="variables[0]",
        )
    ) == 41


def test_metadata_create_variable_uses_resolved_values():
    connection = FakeConnection(returned_id=41)
    context = ApplyContext()

    item = ResolvedPlanItem(
        plan_id="variables[0]",
        resource_type="variable",
        action=PlanAction.CREATE,
        values=ResolvedVariableValues(
            variable="water_level",
            derived=False,
            description="Water-table level",
        ),
    )

    create_metadata_item(
        connection,
        item,
        context,
    )

    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert "INSERT INTO variables" in query
    assert "RETURNING variable_id" in query
    assert params == (
        "water_level",
        False,
        "Water-table level",
    )

