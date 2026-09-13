from datetime import datetime, timezone

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
    ExistingRef,
    FieldChange,
    PlanAction,
    PlannedRef,
    ResolvedDeploymentValues,
    ResolvedLocationLabelValues,
    ResolvedLocationTypeValues,
    ResolvedLocationValues,
    ResolvedPlanItem,
    ResolvedSensorModelValues,
    ResolvedSensorTypeValues,
    ResolvedSensorValues,
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


def test_metadata_create_persists_sensor_model_with_existing_sensor_type():
    connection = FakeConnection(returned_id=51)
    context = ApplyContext()

    item = ResolvedPlanItem(
        plan_id="sensor_models[0]",
        resource_type="sensor_model",
        action=PlanAction.CREATE,
        values=ResolvedSensorModelValues(
            model="CS451",
            manufacturer="Campbell Scientific",
            sensor_type=ExistingRef(
                resource_type="sensor_type",
                database_id=31,
            ),
        ),
    )

    result = create_metadata_item(
        connection,
        item,
        context,
    )

    assert result == ApplyItemResult(
        plan_id="sensor_models[0]",
        resource_type="sensor_model",
        action=PlanAction.CREATE,
        database_id=51,
    )

    query, params = connection.calls[0]

    assert "INSERT INTO sensor_models" in query
    assert "RETURNING sensor_model_id" in query
    assert params == (
        "CS451",
        "Campbell Scientific",
        31,
    )


def test_metadata_create_sensor_model_resolves_planned_sensor_type():
    connection = FakeConnection(returned_id=51)
    context = ApplyContext()

    context.register(
        plan_id="sensor_types[0]",
        resource_type="sensor_type",
        database_id=31,
    )

    item = ResolvedPlanItem(
        plan_id="sensor_models[0]",
        resource_type="sensor_model",
        action=PlanAction.CREATE,
        values=ResolvedSensorModelValues(
            model="CS451",
            manufacturer="Campbell Scientific",
            sensor_type=PlannedRef(
                resource_type="sensor_type",
                plan_id="sensor_types[0]",
            ),
        ),
    )

    create_metadata_item(
        connection,
        item,
        context,
    )

    _, params = connection.calls[0]

    assert params == (
        "CS451",
        "Campbell Scientific",
        31,
    )


def test_metadata_create_persists_sensor_with_existing_sensor_model():
    connection = FakeConnection(returned_id=61)
    context = ApplyContext()

    item = ResolvedPlanItem(
        plan_id="sensors[0]",
        resource_type="sensor",
        action=PlanAction.CREATE,
        values=ResolvedSensorValues(
            sensor_model=ExistingRef(
                resource_type="sensor_model",
                database_id=51,
            ),
            serial_number="SN-001",
            description="Main water-level sensor",
        ),
    )

    result = create_metadata_item(
        connection,
        item,
        context,
    )

    assert result == ApplyItemResult(
        plan_id="sensors[0]",
        resource_type="sensor",
        action=PlanAction.CREATE,
        database_id=61,
    )

    query, params = connection.calls[0]

    assert "INSERT INTO sensors" in query
    assert "RETURNING sensor_id" in query
    assert params == (
        51,
        "SN-001",
        "Main water-level sensor",
    )


def test_metadata_create_sensor_resolves_planned_sensor_model():
    connection = FakeConnection(returned_id=61)
    context = ApplyContext()

    context.register(
        plan_id="sensor_models[0]",
        resource_type="sensor_model",
        database_id=51,
    )

    item = ResolvedPlanItem(
        plan_id="sensors[0]",
        resource_type="sensor",
        action=PlanAction.CREATE,
        values=ResolvedSensorValues(
            sensor_model=PlannedRef(
                resource_type="sensor_model",
                plan_id="sensor_models[0]",
            ),
            serial_number="SN-001",
            description="Main water-level sensor",
        ),
    )

    create_metadata_item(
        connection,
        item,
        context,
    )

    _, params = connection.calls[0]

    assert params == (
        51,
        "SN-001",
        "Main water-level sensor",
    )


def test_metadata_create_persists_location_with_existing_dependencies():
    connection = FakeConnection(returned_id=71)
    context = ApplyContext()

    item = ResolvedPlanItem(
        plan_id="locations[0]",
        resource_type="location",
        action=PlanAction.CREATE,
        values=ResolvedLocationValues(
            site=ExistingRef(
                resource_type="site",
                database_id=11,
            ),
            location_type=ExistingRef(
                resource_type="location_type",
                database_id=21,
            ),
            latitude=54.123,
            longitude=13.456,
            height_above_ground=1.5,
            azimuth=180.0,
        ),
    )

    result = create_metadata_item(
        connection,
        item,
        context,
    )

    assert result == ApplyItemResult(
        plan_id="locations[0]",
        resource_type="location",
        action=PlanAction.CREATE,
        database_id=71,
    )

    assert context.resolve(
        PlannedRef(
            resource_type="location",
            plan_id="locations[0]",
        )
    ) == 71

    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert "INSERT INTO locations" in query
    assert "RETURNING location_id" in query
    assert params == (
        11,
        21,
        54.123,
        13.456,
        1.5,
        180.0,
    )


def test_metadata_create_location_resolves_planned_dependencies():
    connection = FakeConnection(returned_id=71)
    context = ApplyContext()

    context.register(
        plan_id="sites[0]",
        resource_type="site",
        database_id=11,
    )
    context.register(
        plan_id="location_types[0]",
        resource_type="location_type",
        database_id=21,
    )

    item = ResolvedPlanItem(
        plan_id="locations[0]",
        resource_type="location",
        action=PlanAction.CREATE,
        values=ResolvedLocationValues(
            site=PlannedRef(
                resource_type="site",
                plan_id="sites[0]",
            ),
            location_type=PlannedRef(
                resource_type="location_type",
                plan_id="location_types[0]",
            ),
            latitude=None,
            longitude=None,
            height_above_ground=0.0,
            azimuth=None,
        ),
    )

    create_metadata_item(
        connection,
        item,
        context,
    )

    _, params = connection.calls[0]

    assert params == (
        11,
        21,
        None,
        None,
        0.0,
        None,
    )


def test_metadata_create_persists_location_label_with_existing_location():
    connection = FakeConnection(returned_id=81)
    context = ApplyContext()

    valid_from = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )

    item = ResolvedPlanItem(
        plan_id="location_labels[0]",
        resource_type="location_label",
        action=PlanAction.CREATE,
        values=ResolvedLocationLabelValues(
            location=ExistingRef(
                resource_type="location",
                database_id=71,
            ),
            label="Tree 12",
            valid_from=valid_from,
            valid_to=None,
        ),
    )

    result = create_metadata_item(
        connection,
        item,
        context,
    )

    assert result == ApplyItemResult(
        plan_id="location_labels[0]",
        resource_type="location_label",
        action=PlanAction.CREATE,
        database_id=81,
    )

    assert context.resolve(
        PlannedRef(
            resource_type="location_label",
            plan_id="location_labels[0]",
        )
    ) == 81

    query, params = connection.calls[0]

    assert "INSERT INTO location_labels" in query
    assert "RETURNING location_label_id" in query
    assert params == (
        71,
        "Tree 12",
        valid_from,
        None,
    )


def test_metadata_create_location_label_resolves_planned_location():
    connection = FakeConnection(returned_id=81)
    context = ApplyContext()

    context.register(
        plan_id="locations[0]",
        resource_type="location",
        database_id=71,
    )

    valid_from = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )
    valid_to = datetime(
        2027,
        1,
        1,
        tzinfo=timezone.utc,
    )

    item = ResolvedPlanItem(
        plan_id="locations[0].initial_label",
        resource_type="location_label",
        action=PlanAction.CREATE,
        values=ResolvedLocationLabelValues(
            location=PlannedRef(
                resource_type="location",
                plan_id="locations[0]",
            ),
            label="Tree 12",
            valid_from=valid_from,
            valid_to=valid_to,
        ),
    )

    create_metadata_item(
        connection,
        item,
        context,
    )

    _, params = connection.calls[0]

    assert params == (
        71,
        "Tree 12",
        valid_from,
        valid_to,
    )


def test_metadata_create_persists_deployment_with_existing_dependencies():
    connection = FakeConnection(returned_id=91)
    context = ApplyContext()

    valid_from = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )

    item = ResolvedPlanItem(
        plan_id="deployments[0]",
        resource_type="deployment",
        action=PlanAction.CREATE,
        values=ResolvedDeploymentValues(
            sensor=ExistingRef(
                resource_type="sensor",
                database_id=61,
            ),
            location=ExistingRef(
                resource_type="location",
                database_id=71,
            ),
            variable=ExistingRef(
                resource_type="variable",
                database_id=41,
            ),
            valid_from=valid_from,
            valid_to=None,
        ),
    )

    result = create_metadata_item(
        connection,
        item,
        context,
    )

    assert result == ApplyItemResult(
        plan_id="deployments[0]",
        resource_type="deployment",
        action=PlanAction.CREATE,
        database_id=91,
    )

    assert context.resolve(
        PlannedRef(
            resource_type="deployment",
            plan_id="deployments[0]",
        )
    ) == 91

    assert len(connection.calls) == 1

    query, params = connection.calls[0]

    assert "INSERT INTO deployments" in query
    assert "RETURNING deployment_id" in query
    assert params == (
        61,
        71,
        41,
        valid_from,
        None,
    )


def test_metadata_create_deployment_resolves_planned_dependencies():
    connection = FakeConnection(returned_id=91)
    context = ApplyContext()

    context.register(
        plan_id="sensors[0]",
        resource_type="sensor",
        database_id=61,
    )
    context.register(
        plan_id="locations[0]",
        resource_type="location",
        database_id=71,
    )
    context.register(
        plan_id="variables[0]",
        resource_type="variable",
        database_id=41,
    )

    valid_from = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )
    valid_to = datetime(
        2027,
        1,
        1,
        tzinfo=timezone.utc,
    )

    item = ResolvedPlanItem(
        plan_id="deployments[0]",
        resource_type="deployment",
        action=PlanAction.CREATE,
        values=ResolvedDeploymentValues(
            sensor=PlannedRef(
                resource_type="sensor",
                plan_id="sensors[0]",
            ),
            location=PlannedRef(
                resource_type="location",
                plan_id="locations[0]",
            ),
            variable=PlannedRef(
                resource_type="variable",
                plan_id="variables[0]",
            ),
            valid_from=valid_from,
            valid_to=valid_to,
        ),
    )

    create_metadata_item(
        connection,
        item,
        context,
    )

    _, params = connection.calls[0]

    assert params == (
        61,
        71,
        41,
        valid_from,
        valid_to,
    )


class SequencedFakeConnection:
    def __init__(self, returned_ids):
        self.returned_ids = iter(returned_ids)
        self.calls = []
        self._current_id = None

    def execute(self, query, params):
        self.calls.append((query, params))
        self._current_id = next(self.returned_ids)
        return self

    def fetchone(self):
        return (self._current_id,)


def test_metadata_create_dispatch_preserves_dependency_chain_order():
    connection = SequencedFakeConnection(
        returned_ids=[31, 51, 61, 91],
    )
    context = ApplyContext()

    valid_from = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )

    items = (
        ResolvedPlanItem(
            plan_id="sensor_types[0]",
            resource_type="sensor_type",
            action=PlanAction.CREATE,
            values=ResolvedSensorTypeValues(
                type="pressure transducer",
                description="Water-level pressure sensor",
            ),
        ),
        ResolvedPlanItem(
            plan_id="sensor_models[0]",
            resource_type="sensor_model",
            action=PlanAction.CREATE,
            values=ResolvedSensorModelValues(
                model="CS451",
                manufacturer="Campbell Scientific",
                sensor_type=PlannedRef(
                    resource_type="sensor_type",
                    plan_id="sensor_types[0]",
                ),
            ),
        ),
        ResolvedPlanItem(
            plan_id="sensors[0]",
            resource_type="sensor",
            action=PlanAction.CREATE,
            values=ResolvedSensorValues(
                sensor_model=PlannedRef(
                    resource_type="sensor_model",
                    plan_id="sensor_models[0]",
                ),
                serial_number="SN-001",
                description="Main water-level sensor",
            ),
        ),
        ResolvedPlanItem(
            plan_id="deployments[0]",
            resource_type="deployment",
            action=PlanAction.CREATE,
            values=ResolvedDeploymentValues(
                sensor=PlannedRef(
                    resource_type="sensor",
                    plan_id="sensors[0]",
                ),
                location=ExistingRef(
                    resource_type="location",
                    database_id=71,
                ),
                variable=ExistingRef(
                    resource_type="variable",
                    database_id=41,
                ),
                valid_from=valid_from,
                valid_to=None,
            ),
        ),
    )

    results = tuple(
        create_metadata_item(
            connection,
            item,
            context,
        )
        for item in items
    )

    assert [
        result.plan_id
        for result in results
    ] == [
        "sensor_types[0]",
        "sensor_models[0]",
        "sensors[0]",
        "deployments[0]",
    ]

    assert [
        result.database_id
        for result in results
    ] == [
        31,
        51,
        61,
        91,
    ]

    assert context.resolve(
        PlannedRef(
            resource_type="sensor_type",
            plan_id="sensor_types[0]",
        )
    ) == 31

    assert context.resolve(
        PlannedRef(
            resource_type="sensor_model",
            plan_id="sensor_models[0]",
        )
    ) == 51

    assert context.resolve(
        PlannedRef(
            resource_type="sensor",
            plan_id="sensors[0]",
        )
    ) == 61

    assert context.resolve(
        PlannedRef(
            resource_type="deployment",
            plan_id="deployments[0]",
        )
    ) == 91

    _, sensor_model_params = connection.calls[1]
    assert sensor_model_params == (
        "CS451",
        "Campbell Scientific",
        31,
    )

    _, sensor_params = connection.calls[2]
    assert sensor_params == (
        51,
        "SN-001",
        "Main water-level sensor",
    )

    _, deployment_params = connection.calls[3]
    assert deployment_params == (
        61,
        71,
        41,
        valid_from,
        None,
    )


def test_metadata_create_dispatch_handles_location_chain():
    connection = SequencedFakeConnection(
        returned_ids=[11, 21, 71, 81],
    )
    context = ApplyContext()

    valid_from = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )

    items = (
        ResolvedPlanItem(
            plan_id="sites[0]",
            resource_type="site",
            action=PlanAction.CREATE,
            values=ResolvedSiteValues(
                site_code="SAN",
                name="Sandhagen",
            ),
        ),
        ResolvedPlanItem(
            plan_id="location_types[0]",
            resource_type="location_type",
            action=PlanAction.CREATE,
            values=ResolvedLocationTypeValues(
                type="plot",
                description="Monitoring plot",
            ),
        ),
        ResolvedPlanItem(
            plan_id="locations[0]",
            resource_type="location",
            action=PlanAction.CREATE,
            values=ResolvedLocationValues(
                site=PlannedRef(
                    resource_type="site",
                    plan_id="sites[0]",
                ),
                location_type=PlannedRef(
                    resource_type="location_type",
                    plan_id="location_types[0]",
                ),
                latitude=None,
                longitude=None,
                height_above_ground=0.0,
                azimuth=None,
            ),
        ),
        ResolvedPlanItem(
            plan_id="locations[0].initial_label",
            resource_type="location_label",
            action=PlanAction.CREATE,
            values=ResolvedLocationLabelValues(
                location=PlannedRef(
                    resource_type="location",
                    plan_id="locations[0]",
                ),
                label="Tree 12",
                valid_from=valid_from,
                valid_to=None,
            ),
        ),
    )

    results = tuple(
        create_metadata_item(
            connection,
            item,
            context,
        )
        for item in items
    )

    assert [
        result.database_id
        for result in results
    ] == [
        11,
        21,
        71,
        81,
    ]

    _, location_params = connection.calls[2]
    assert location_params == (
        11,
        21,
        None,
        None,
        0.0,
        None,
    )

    _, label_params = connection.calls[3]
    assert label_params == (
        71,
        "Tree 12",
        valid_from,
        None,
    )

