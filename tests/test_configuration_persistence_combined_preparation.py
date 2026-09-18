from dataclasses import replace
from datetime import datetime, timezone

import pytest

from dendroflow import database
from dendroflow.configuration.persistence.combined_preparation import (
    prepare_plan,
)
from dendroflow.configuration.persistence.models import (
    ApplyError,
    ApplyErrorCode,
)
from dendroflow.configuration.persistence.preparation import (
    prepare_metadata_plan,
)
from dendroflow.configuration.persistence.raw_preparation import (
    prepare_raw_plan,
)
from dendroflow.configuration.plan import (
    ExistingRef,
    FieldChange,
    PlanAction,
    PlanError,
    PlanErrorCode,
    PlannedRef,
    ResolvedDeploymentValues,
    ResolvedFileValues,
    ResolvedInterfaceValues,
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSiteValues,
)


@pytest.fixture(autouse=True)
def forbid_database_connections(monkeypatch):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("combined preparation must not connect")

    monkeypatch.setattr(database, "connect", unexpected_connection)


def site_item(plan_id="site", *, parent=None):
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="site",
        action=PlanAction.CREATE,
        values=ResolvedSiteValues(
            site_code=plan_id,
            name=plan_id,
            parent=parent,
        ),
    )


def deployment_item():
    return ResolvedPlanItem(
        plan_id="deployment",
        resource_type="deployment",
        action=PlanAction.CREATE,
        values=ResolvedDeploymentValues(
            sensor=ExistingRef("sensor", 1),
            location=ExistingRef("location", 2),
            variable=ExistingRef("variable", 3),
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            valid_to=None,
        ),
    )


def file_item():
    return ResolvedPlanItem(
        plan_id="file",
        resource_type="file",
        action=PlanAction.CREATE,
        values=ResolvedFileValues(
            filepath="/data/measurements.csv",
            timestamp_timezone="UTC",
            timestamp_format="%Y-%m-%d %H:%M:%S",
            reader_config={"reader": "csv", "options": {}},
        ),
    )


def interface_item():
    return ResolvedPlanItem(
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


def combined_plan():
    return ResolvedPlan(
        metadata_items=(deployment_item(),),
        raw_items=(interface_item(), file_item()),
    )


def assert_invalid(plan, **kwargs):
    with pytest.raises(ApplyError) as caught:
        prepare_plan(plan, **kwargs)

    assert caught.value.code == ApplyErrorCode.PLAN_NOT_APPLICABLE


@pytest.mark.parametrize(
    ("has_metadata", "has_raw"),
    [
        (False, False),
        (True, False),
        (False, True),
        (True, True),
    ],
    ids=["empty", "metadata-only", "raw-only", "both"],
)
def test_prepares_all_plan_shapes(has_metadata, has_raw):
    plan = ResolvedPlan(
        metadata_items=(site_item(),) if has_metadata else (),
        raw_items=(file_item(),) if has_raw else (),
    )

    prepared = prepare_plan(plan)

    assert prepared.metadata.items == plan.metadata_items
    assert prepared.raw.items == plan.raw_items
    assert prepared.items == plan.items
    assert prepared.metadata.requires_writes is has_metadata
    assert prepared.raw.requires_writes is has_raw
    assert prepared.requires_writes is (has_metadata or has_raw)


def test_reuse_only_plan_requires_no_writes():
    plan = ResolvedPlan(
        metadata_items=(
            replace(
                site_item(),
                action=PlanAction.REUSE,
                database_id=11,
            ),
        ),
        raw_items=(
            replace(
                file_item(),
                action=PlanAction.REUSE,
                database_id=17,
            ),
        ),
    )

    prepared = prepare_plan(plan)

    assert prepared.items == plan.items
    assert prepared.metadata.requires_writes is False
    assert prepared.raw.requires_writes is False
    assert prepared.requires_writes is False


def test_preserves_original_items_and_both_execution_orders():
    parent = site_item("parent")
    child = site_item(
        "child",
        parent=PlannedRef("site", "parent"),
    )
    deployment = deployment_item()
    interface = interface_item()
    file = file_item()
    plan = ResolvedPlan(
        metadata_items=(child, parent, deployment),
        raw_items=(interface, file),
    )

    prepared = prepare_plan(plan)

    assert prepared.metadata.items == (child, parent, deployment)
    assert prepared.metadata.execution_items == (
        parent,
        child,
        deployment,
    )
    assert prepared.raw.items == (interface, file)
    assert prepared.raw.execution_items == (file, interface)
    assert prepared.raw.required_metadata_plan_ids == ("deployment",)
    assert prepared.items == (child, parent, deployment, interface, file)

    assert plan.metadata_items == (child, parent, deployment)
    assert plan.raw_items == (interface, file)


@pytest.mark.parametrize("confirmed", [False, True])
def test_plan_errors_are_rejected_even_with_confirmation(confirmed):
    plan = replace(
        combined_plan(),
        errors=(
            PlanError(
                code=PlanErrorCode.CONFLICT,
                resource_type="file",
                source_path="files[0]",
                message="Conflicting reader settings",
            ),
        ),
    )

    assert_invalid(
        plan,
        confirm_identity_changes=confirmed,
    )


@pytest.mark.parametrize("stage", ["metadata", "raw"])
@pytest.mark.parametrize("confirmed", [False, True])
def test_confirmation_checks_include_both_stages(stage, confirmed):
    if stage == "metadata":
        update = replace(
            site_item(),
            action=PlanAction.UPDATE,
            database_id=11,
            changes=(
                FieldChange(
                    field="site_code",
                    before="old-site",
                    after="site",
                    identity_change=True,
                ),
            ),
        )
        plan = ResolvedPlan(
            metadata_items=(update,),
            raw_items=(file_item(),),
        )
    else:
        plan = ResolvedPlan(
            metadata_items=(site_item(),),
            raw_items=(
                replace(file_item(), confirmation_required=True),
            ),
        )

    if confirmed:
        prepared = prepare_plan(
            plan,
            confirm_identity_changes=True,
        )
        assert prepared.items == plan.items
    else:
        with pytest.raises(ApplyError) as caught:
            prepare_plan(plan)

        assert caught.value.code == ApplyErrorCode.CONFIRMATION_REQUIRED


@pytest.mark.parametrize("invalid_stage", ["metadata", "raw"])
def test_invalid_stage_prevents_combined_preparation(invalid_stage):
    metadata = site_item()
    raw = file_item()

    if invalid_stage == "metadata":
        metadata = replace(metadata, values=object())
    else:
        raw = replace(
            raw,
            values=replace(raw.values, reader_config=[]),
        )

    assert_invalid(
        ResolvedPlan(
            metadata_items=(metadata,),
            raw_items=(raw,),
        )
    )


def test_duplicate_plan_ids_across_stages_are_rejected():
    assert_invalid(
        ResolvedPlan(
            metadata_items=(site_item("shared"),),
            raw_items=(replace(file_item(), plan_id="shared"),),
        )
    )


def test_metadata_dependency_cycle_is_rejected():
    assert_invalid(
        ResolvedPlan(
            metadata_items=(
                site_item(
                    "first",
                    parent=PlannedRef("site", "second"),
                ),
                site_item(
                    "second",
                    parent=PlannedRef("site", "first"),
                ),
            ),
            raw_items=(file_item(),),
        )
    )


def test_referenced_deployment_gets_full_metadata_preparation():
    deployment = deployment_item()
    deployment = replace(
        deployment,
        values=replace(
            deployment.values,
            sensor=PlannedRef("sensor", "missing-sensor"),
        ),
    )
    plan = replace(
        combined_plan(),
        metadata_items=(deployment,),
    )

    # RAW preparation recognizes the deployment CREATE target.
    # Combined preparation must also reject its missing sensor.
    assert_invalid(plan)


def test_planned_deployment_cannot_target_reuse():
    deployment = replace(
        deployment_item(),
        action=PlanAction.REUSE,
        database_id=91,
    )
    plan = replace(
        combined_plan(),
        metadata_items=(deployment,),
    )

    assert_invalid(plan)


@pytest.mark.parametrize(
    "prepare",
    [prepare_metadata_plan, prepare_raw_plan],
    ids=["metadata-only", "raw-only"],
)
def test_standalone_preparation_still_rejects_combined_plans(prepare):
    with pytest.raises(ApplyError) as caught:
        prepare(combined_plan())

    assert caught.value.code == ApplyErrorCode.PLAN_NOT_APPLICABLE
