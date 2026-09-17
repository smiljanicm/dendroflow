from dataclasses import replace
from datetime import datetime, timezone

import pytest

from dendroflow import database
from dendroflow.configuration.persistence.models import (
    ApplyError,
    ApplyErrorCode,
)
from dendroflow.configuration.persistence.preparation import (
    prepare_metadata_plan,
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
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSensorModelValues,
    ResolvedSensorTypeValues,
    ResolvedSensorValues,
    ResolvedSiteValues,
    ResolvedVariableValues,
)


@pytest.fixture(autouse=True)
def forbid_database_connections(monkeypatch):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("ordering must not open a database connection")

    monkeypatch.setattr(database, "connect", unexpected_connection)


def _create(resource_type, plan_id, **overrides):
    defaults = {
        "site": ResolvedSiteValues(
            site_code=plan_id,
            name=plan_id,
        ),
        "location_type": ResolvedLocationTypeValues(type="stem"),
        "sensor_type": ResolvedSensorTypeValues(type="dendrometer"),
        "variable": ResolvedVariableValues(variable="diameter"),
        "sensor_model": ResolvedSensorModelValues(
            model="M1",
            manufacturer="Acme",
            sensor_type=ExistingRef("sensor_type", 11),
        ),
        "sensor": ResolvedSensorValues(
            serial_number="S1",
            sensor_model=ExistingRef("sensor_model", 21),
        ),
        "location": ResolvedLocationValues(
            site=ExistingRef("site", 31),
            location_type=ExistingRef("location_type", 41),
        ),
        "location_label": ResolvedLocationLabelValues(
            location=ExistingRef("location", 51),
            label="Tree 1",
            valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
        ),
        "deployment": ResolvedDeploymentValues(
            sensor=ExistingRef("sensor", 61),
            location=ExistingRef("location", 51),
            variable=ExistingRef("variable", 71),
            valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
        ),
    }

    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type=resource_type,
        action=PlanAction.CREATE,
        values=replace(defaults[resource_type], **overrides),
    )


def _prepare(*items):
    return prepare_metadata_plan(
        ResolvedPlan(metadata_items=items),
    )


@pytest.mark.parametrize(
    ("owner_type", "field", "target_type"),
    [
        ("site", "parent", "site"),
        ("sensor_model", "sensor_type", "sensor_type"),
        ("sensor", "sensor_model", "sensor_model"),
        ("location", "site", "site"),
        ("location", "location_type", "location_type"),
        ("location_label", "location", "location"),
        ("deployment", "sensor", "sensor"),
        ("deployment", "location", "location"),
        ("deployment", "variable", "variable"),
    ],
)
def test_metadata_ordering_places_relationship_creator_first(
    owner_type,
    field,
    target_type,
):
    target = _create(target_type, "target")
    owner = _create(
        owner_type,
        "owner",
        **{field: PlannedRef(target_type, "target")},
    )

    prepared = _prepare(owner, target)

    assert prepared.items == (owner, target)
    assert prepared.execution_items == (target, owner)


def test_metadata_ordering_handles_dependency_chain():
    sensor_type = _create("sensor_type", "sensor_types[0]")
    model = _create(
        "sensor_model",
        "sensor_models[0]",
        sensor_type=PlannedRef("sensor_type", sensor_type.plan_id),
    )
    sensor = _create(
        "sensor",
        "sensors[0]",
        sensor_model=PlannedRef("sensor_model", model.plan_id),
    )
    deployment = _create(
        "deployment",
        "deployments[0]",
        sensor=PlannedRef("sensor", sensor.plan_id),
    )

    prepared = _prepare(deployment, sensor, model, sensor_type)

    assert prepared.execution_items == (
        sensor_type,
        model,
        sensor,
        deployment,
    )
    assert prepared.items == (deployment, sensor, model, sensor_type)


def test_metadata_ordering_selects_earliest_currently_ready_item():
    parent = _create("site", "parent")
    child = _create(
        "site",
        "child",
        parent=PlannedRef("site", "parent"),
    )
    independent = _create("variable", "independent")

    prepared = _prepare(child, parent, independent)

    assert prepared.execution_items == (parent, child, independent)


def test_metadata_ordering_needs_no_creator_for_existing_reference():
    sensor = _create(
        "sensor",
        "sensors[0]",
        sensor_model=ExistingRef("sensor_model", 21),
    )

    prepared = _prepare(sensor)

    assert prepared.execution_items == (sensor,)


def test_metadata_ordering_places_creator_before_relationship_update():
    model = _create("sensor_model", "sensor_models[0]")
    reference = PlannedRef("sensor_model", model.plan_id)

    sensor = _create(
        "sensor",
        "updates.sensors[0]",
        sensor_model=reference,
    )
    sensor = replace(
        sensor,
        action=PlanAction.UPDATE,
        database_id=61,
        changes=(
            FieldChange(
                field="sensor_model",
                before=ExistingRef("sensor_model", 21),
                after=reference,
                identity_change=True,
            ),
        ),
    )

    prepared = prepare_metadata_plan(
        ResolvedPlan(metadata_items=(sensor, model)),
        confirm_identity_changes=True,
    )

    assert prepared.items == (sensor, model)
    assert prepared.execution_items == (model, sensor)


def test_metadata_ordering_rejects_missing_planned_target():
    sensor = _create(
        "sensor",
        "sensors[0]",
        sensor_model=PlannedRef("sensor_model", "missing"),
    )

    with pytest.raises(ApplyError, match="matching METADATA CREATE"):
        _prepare(sensor)


def test_metadata_ordering_rejects_wrong_target_resource():
    wrong_target = _create("site", "target")
    sensor = _create(
        "sensor",
        "sensors[0]",
        sensor_model=PlannedRef("sensor_model", "target"),
    )

    with pytest.raises(ApplyError, match="matching METADATA CREATE"):
        _prepare(sensor, wrong_target)


@pytest.mark.parametrize(
    "action",
    [PlanAction.REUSE, PlanAction.UPDATE],
)
def test_metadata_ordering_requires_create_target(action):
    target = _create("site", "target")
    changes = ()

    if action == PlanAction.UPDATE:
        changes = (
            FieldChange(
                field="name",
                before="Old name",
                after=target.values.name,
            ),
        )

    target = replace(
        target,
        action=action,
        database_id=31,
        changes=changes,
    )
    child = _create(
        "site",
        "child",
        parent=PlannedRef("site", "target"),
    )

    with pytest.raises(ApplyError, match="matching METADATA CREATE"):
        _prepare(child, target)


@pytest.mark.parametrize(
    "reference",
    [
        ExistingRef("site", 31),
        PlannedRef("site", "target"),
    ],
)
def test_metadata_ordering_checks_relationship_resource_type(reference):
    sensor = _create(
        "sensor",
        "sensors[0]",
        sensor_model=reference,
    )
    target = _create("site", "target")

    with pytest.raises(
        ApplyError,
        match="requires a sensor_model reference",
    ):
        _prepare(sensor, target)


@pytest.mark.parametrize("self_reference", [False, True])
def test_metadata_ordering_rejects_cycles(self_reference):
    first = _create(
        "site",
        "first",
        parent=PlannedRef(
            "site",
            "first" if self_reference else "second",
        ),
    )
    second = _create(
        "site",
        "second",
        parent=PlannedRef("site", "first"),
    )
    items = (first,) if self_reference else (first, second)

    with pytest.raises(ApplyError, match="dependency cycle") as caught:
        _prepare(*items)

    assert caught.value.code == ApplyErrorCode.PLAN_NOT_APPLICABLE
    assert "first" in str(caught.value)


def test_metadata_ordering_rejects_planned_relationship_on_reuse():
    parent = _create("site", "parent")
    reused = _create(
        "site",
        "reused",
        parent=PlannedRef("site", "parent"),
    )
    reused = replace(
        reused,
        action=PlanAction.REUSE,
        database_id=31,
    )

    with pytest.raises(
        ApplyError,
        match="REUSE cannot depend on a planned resource",
    ):
        _prepare(reused, parent)
