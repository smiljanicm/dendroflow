from dataclasses import replace

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
    ResolvedLocationTypeValues,
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
        pytest.fail("constraint ordering must not open a connection")

    monkeypatch.setattr(database, "connect", unexpected_connection)


def _item(
    resource_type,
    plan_id,
    values,
    *,
    action=PlanAction.CREATE,
    database_id=None,
    changes=(),
):
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type=resource_type,
        action=action,
        database_id=database_id,
        values=values,
        changes=changes,
    )


def _prepare(*items):
    return prepare_metadata_plan(
        ResolvedPlan(metadata_items=items),
        confirm_identity_changes=True,
    )


def _site_update(plan_id, database_id, before, after):
    return _item(
        "site",
        plan_id,
        ResolvedSiteValues(site_code=after, name=plan_id),
        action=PlanAction.UPDATE,
        database_id=database_id,
        changes=(
            FieldChange(
                field="site_code",
                before=before,
                after=after,
                identity_change=True,
            ),
        ),
    )


@pytest.fixture(
    params=[
        ("site", "site_code"),
        ("location_type", "type"),
        ("sensor_type", "type"),
        ("variable", "variable"),
        ("sensor_model", "manufacturer"),
        ("sensor_model", "model"),
        ("sensor", "serial_number"),
        ("sensor", "sensor_model"),
    ],
)
def unique_case(request):
    resource_type, field = request.param

    defaults = {
        "site": ResolvedSiteValues(site_code="BASE", name="Site"),
        "location_type": ResolvedLocationTypeValues(type="BASE"),
        "sensor_type": ResolvedSensorTypeValues(type="BASE"),
        "variable": ResolvedVariableValues(variable="BASE"),
        "sensor_model": ResolvedSensorModelValues(
            manufacturer="Acme",
            model="M1",
            sensor_type=ExistingRef("sensor_type", 31),
        ),
        "sensor": ResolvedSensorValues(
            serial_number="S1",
            sensor_model=ExistingRef("sensor_model", 21),
        ),
    }

    if field == "sensor_model":
        old = ExistingRef("sensor_model", 21)
        new = ExistingRef("sensor_model", 22)
        other = ExistingRef("sensor_model", 23)
    else:
        old, new, other = "OLD", "NEW", "OTHER"

    values = replace(defaults[resource_type], **{field: new})

    return resource_type, field, values, old, other


@pytest.mark.parametrize(
    "claimant_action",
    [PlanAction.CREATE, PlanAction.UPDATE],
    ids=["create-claimant", "update-claimant"],
)
def test_unique_key_release_precedes_claimant(
    unique_case,
    claimant_action,
):
    resource_type, field, values, old, other = unique_case

    holder = _item(
        resource_type,
        "holder",
        values,
        action=PlanAction.UPDATE,
        database_id=11,
        changes=(
            FieldChange(
                field=field,
                before=old,
                after=getattr(values, field),
                identity_change=True,
            ),
        ),
    )

    claimant_values = replace(values, **{field: old})
    claimant_changes = ()
    claimant_id = None

    if claimant_action == PlanAction.UPDATE:
        claimant_id = 12
        claimant_changes = (
            FieldChange(
                field=field,
                before=other,
                after=old,
                identity_change=True,
            ),
        )

    claimant = _item(
        resource_type,
        "claimant",
        claimant_values,
        action=claimant_action,
        database_id=claimant_id,
        changes=claimant_changes,
    )

    prepared = _prepare(claimant, holder)

    assert prepared.items == (claimant, holder)
    assert prepared.execution_items == (holder, claimant)


@pytest.mark.parametrize("resource_type", ["sensor_model", "sensor"])
def test_composite_unique_key_compares_unchanged_component(resource_type):
    if resource_type == "sensor_model":
        field = "model"
        holder_values = ResolvedSensorModelValues(
            manufacturer="Acme",
            model="NEW",
            sensor_type=ExistingRef("sensor_type", 31),
        )
        claimant_values = replace(
            holder_values,
            manufacturer="Other manufacturer",
            model="OLD",
        )
    else:
        field = "serial_number"
        holder_values = ResolvedSensorValues(
            serial_number="NEW",
            sensor_model=ExistingRef("sensor_model", 21),
        )
        claimant_values = replace(
            holder_values,
            serial_number="OLD",
            sensor_model=ExistingRef("sensor_model", 22),
        )

    holder = _item(
        resource_type,
        "holder",
        holder_values,
        action=PlanAction.UPDATE,
        database_id=11,
        changes=(
            FieldChange(
                field=field,
                before="OLD",
                after="NEW",
                identity_change=True,
            ),
        ),
    )
    claimant = _item(resource_type, "claimant", claimant_values)

    prepared = _prepare(claimant, holder)

    assert prepared.execution_items == (claimant, holder)


def test_unique_key_swap_is_rejected_as_dependency_cycle():
    first = _site_update("first", 11, "A", "B")
    second = _site_update("second", 12, "B", "A")

    with pytest.raises(ApplyError, match="dependency cycle") as caught:
        _prepare(first, second)

    assert caught.value.code == ApplyErrorCode.PLAN_NOT_APPLICABLE
    assert "first" in str(caught.value)
    assert "second" in str(caught.value)


def test_unique_key_release_chain_is_ordered():
    first = _site_update("first", 11, "A", "B")
    second = _site_update("second", 12, "B", "C")
    third = _site_update("third", 13, "C", "D")

    prepared = _prepare(first, second, third)

    assert prepared.items == (first, second, third)
    assert prepared.execution_items == (third, second, first)


def test_non_identity_update_keeps_original_order():
    updated = _item(
        "site",
        "updated",
        ResolvedSiteValues(site_code="A", name="New name"),
        action=PlanAction.UPDATE,
        database_id=11,
        changes=(
            FieldChange(
                field="name",
                before="Old name",
                after="New name",
            ),
        ),
    )
    created = _item(
        "site",
        "created",
        ResolvedSiteValues(site_code="B", name="Another site"),
    )

    prepared = _prepare(created, updated)

    assert prepared.execution_items == (created, updated)


def test_reuse_snapshot_does_not_block_unique_key_release():
    reused = _item(
        "site",
        "reused",
        ResolvedSiteValues(site_code="A", name="Existing site"),
        action=PlanAction.REUSE,
        database_id=11,
    )
    updated = _site_update("updated", 11, "A", "B")
    created = _item(
        "site",
        "created",
        ResolvedSiteValues(site_code="A", name="Replacement site"),
    )

    prepared = _prepare(created, reused, updated)

    assert prepared.items == (created, reused, updated)
    assert prepared.execution_items == (reused, updated, created)
