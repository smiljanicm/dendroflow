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
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSensorValues,
    ResolvedSiteValues,
)


@pytest.fixture(autouse=True)
def forbid_database_connections(monkeypatch):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("ordering preparation must not open a connection")

    monkeypatch.setattr(database, "connect", unexpected_connection)


def _prepare(items):
    return prepare_metadata_plan(
        ResolvedPlan(metadata_items=items),
        confirm_identity_changes=True,
    )


@pytest.mark.parametrize("reverse_order", [False, True])
def test_unique_release_waits_for_planned_parent(reverse_order):
    parent = ResolvedPlanItem(
        plan_id="parent",
        resource_type="site",
        action=PlanAction.CREATE,
        values=ResolvedSiteValues(
            site_code="PARENT",
            name="Parent",
        ),
    )
    parent_ref = PlannedRef("site", "parent")

    updated = ResolvedPlanItem(
        plan_id="updated",
        resource_type="site",
        action=PlanAction.UPDATE,
        database_id=11,
        values=ResolvedSiteValues(
            site_code="NEW",
            name="Existing site",
            parent=parent_ref,
        ),
        changes=(
            FieldChange(
                "site_code",
                "OLD",
                "NEW",
                identity_change=True,
            ),
            FieldChange("parent", None, parent_ref),
        ),
    )
    replacement = ResolvedPlanItem(
        plan_id="replacement",
        resource_type="site",
        action=PlanAction.CREATE,
        values=ResolvedSiteValues(
            site_code="OLD",
            name="Replacement",
        ),
    )

    items = (replacement, updated, parent)
    if reverse_order:
        items = tuple(reversed(items))

    prepared = _prepare(items)

    assert prepared.items == items
    assert prepared.execution_items == (parent, updated, replacement)


@pytest.mark.parametrize("reverse_order", [False, True])
def test_reference_unique_and_deployment_dependencies_compose(reverse_order):
    model = ExistingRef("sensor_model", 21)
    old_sensor = ExistingRef("sensor", 11)
    new_sensor = PlannedRef("sensor", "new_sensor")
    location = ExistingRef("location", 31)
    variable = ExistingRef("variable", 41)
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)

    renamed_sensor = ResolvedPlanItem(
        plan_id="renamed_sensor",
        resource_type="sensor",
        action=PlanAction.UPDATE,
        database_id=11,
        values=ResolvedSensorValues(
            serial_number="NEW",
            sensor_model=model,
        ),
        changes=(
            FieldChange(
                "serial_number",
                "OLD",
                "NEW",
                identity_change=True,
            ),
        ),
    )
    created_sensor = ResolvedPlanItem(
        plan_id="new_sensor",
        resource_type="sensor",
        action=PlanAction.CREATE,
        values=ResolvedSensorValues(
            serial_number="OLD",
            sensor_model=model,
        ),
    )
    moved_deployment = ResolvedPlanItem(
        plan_id="moved_deployment",
        resource_type="deployment",
        action=PlanAction.UPDATE,
        database_id=51,
        values=ResolvedDeploymentValues(
            sensor=new_sensor,
            location=location,
            variable=variable,
            valid_from=start,
        ),
        changes=(
            FieldChange(
                "sensor",
                old_sensor,
                new_sensor,
                identity_change=True,
            ),
        ),
    )
    replacement_deployment = ResolvedPlanItem(
        plan_id="replacement_deployment",
        resource_type="deployment",
        action=PlanAction.CREATE,
        values=ResolvedDeploymentValues(
            sensor=old_sensor,
            location=location,
            variable=variable,
            valid_from=start,
        ),
    )

    items = (
        replacement_deployment,
        moved_deployment,
        created_sensor,
        renamed_sensor,
    )
    if reverse_order:
        items = tuple(reversed(items))

    prepared = _prepare(items)

    assert prepared.items == items
    assert prepared.execution_items == (
        renamed_sensor,
        created_sensor,
        moved_deployment,
        replacement_deployment,
    )


@pytest.mark.parametrize("reverse_order", [False, True])
def test_combined_reference_and_unique_dependencies_reject_cycle(
    reverse_order,
):
    parent = ResolvedPlanItem(
        plan_id="parent",
        resource_type="site",
        action=PlanAction.CREATE,
        values=ResolvedSiteValues(
            site_code="OLD",
            name="New parent",
        ),
    )
    parent_ref = PlannedRef("site", "parent")

    updated = ResolvedPlanItem(
        plan_id="updated",
        resource_type="site",
        action=PlanAction.UPDATE,
        database_id=11,
        values=ResolvedSiteValues(
            site_code="NEW",
            name="Existing site",
            parent=parent_ref,
        ),
        changes=(
            FieldChange(
                "site_code",
                "OLD",
                "NEW",
                identity_change=True,
            ),
            FieldChange("parent", None, parent_ref),
        ),
    )

    items = (parent, updated)
    if reverse_order:
        items = tuple(reversed(items))

    with pytest.raises(ApplyError, match="dependency cycle") as caught:
        _prepare(items)

    assert caught.value.code == ApplyErrorCode.PLAN_NOT_APPLICABLE
    assert "parent" in str(caught.value)
    assert "updated" in str(caught.value)
