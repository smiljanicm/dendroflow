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
    FieldChange,
    PlanAction,
    PlanError,
    PlanErrorCode,
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSiteValues,
)


@pytest.fixture(autouse=True)
def forbid_database_connections(monkeypatch):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("preparation must not open a database connection")

    monkeypatch.setattr(database, "connect", unexpected_connection)


def _site_item(
    plan_id="sites[0]",
    *,
    action=PlanAction.CREATE,
    database_id=None,
):
    changes = ()

    if action == PlanAction.UPDATE:
        changes = (
            FieldChange(
                field="name",
                before="Old name",
                after="New name",
            ),
        )

    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="site",
        action=action,
        database_id=database_id,
        values=ResolvedSiteValues(
            site_code="SITE_A",
            name="New name",
        ),
        changes=changes,
    )


def test_metadata_preparation_accepts_empty_plan():
    prepared = prepare_metadata_plan(ResolvedPlan())

    assert prepared.items == ()
    assert prepared.requires_writes is False
    assert prepared.execution_items == ()


def test_metadata_preparation_accepts_reuse_only_plan():
    items = (
        _site_item(
            "sites[0]",
            action=PlanAction.REUSE,
            database_id=11,
        ),
        _site_item(
            "sites[1]",
            action=PlanAction.REUSE,
            database_id=12,
        ),
    )

    prepared = prepare_metadata_plan(
        ResolvedPlan(metadata_items=items),
    )

    assert prepared.items == items
    assert prepared.requires_writes is False
    assert prepared.execution_items == items


def test_metadata_preparation_preserves_mixed_plan_order():
    items = (
        _site_item(
            "updates.sites[0]",
            action=PlanAction.UPDATE,
            database_id=11,
        ),
        _site_item(
            "sites[0]",
            action=PlanAction.REUSE,
            database_id=12,
        ),
        _site_item("sites[1]"),
    )

    prepared = prepare_metadata_plan(
        ResolvedPlan(metadata_items=items),
    )

    assert prepared.items == items
    assert prepared.requires_writes is True


@pytest.mark.parametrize("confirmed", [False, True])
def test_metadata_preparation_rejects_plan_errors(confirmed):
    plan = ResolvedPlan(
        metadata_items=(_site_item(),),
        errors=(
            PlanError(
                code=PlanErrorCode.CONFLICT,
                resource_type="site",
                source_path="sites[0]",
                message="site identity conflict",
            ),
        ),
    )

    with pytest.raises(ApplyError) as caught:
        prepare_metadata_plan(
            plan,
            confirm_identity_changes=confirmed,
        )

    assert caught.value.code == ApplyErrorCode.PLAN_NOT_APPLICABLE


@pytest.mark.parametrize("confirmed", [False, True])
def test_metadata_preparation_enforces_confirmation(confirmed):
    item = _site_item(
        "updates.sites[0]",
        action=PlanAction.UPDATE,
        database_id=11,
    )
    item = replace(
        item,
        changes=(
            FieldChange(
                field="site_code",
                before="OLD_CODE",
                after="SITE_A",
                identity_change=True,
            ),
        ),
    )
    plan = ResolvedPlan(metadata_items=(item,))

    if confirmed:
        prepared = prepare_metadata_plan(
            plan,
            confirm_identity_changes=True,
        )
        assert prepared.items == (item,)
        assert prepared.requires_writes is True
    else:
        with pytest.raises(ApplyError) as caught:
            prepare_metadata_plan(plan)

        assert (
            caught.value.code
            == ApplyErrorCode.CONFIRMATION_REQUIRED
        )


def test_metadata_preparation_rejects_raw_items():
    raw_item = ResolvedPlanItem(
        plan_id="files[0]",
        resource_type="file",
        action=PlanAction.REUSE,
        database_id=101,
        values=object(),
    )
    plan = ResolvedPlan(
        metadata_items=(_site_item(),),
        raw_items=(raw_item,),
    )

    with pytest.raises(ApplyError, match="does not accept RAW items"):
        prepare_metadata_plan(plan)


@pytest.mark.parametrize(
    "resource_type",
    ["file", "interface", "unknown"],
)
def test_metadata_preparation_rejects_unsupported_resource(
    resource_type,
):
    item = replace(_site_item(), resource_type=resource_type)

    with pytest.raises(
        ApplyError,
        match="unsupported METADATA resource type",
    ):
        prepare_metadata_plan(
            ResolvedPlan(metadata_items=(item,)),
        )


def test_metadata_preparation_rejects_location_label_update():
    item = replace(
        _site_item(
            "updates.location_labels[0]",
            action=PlanAction.UPDATE,
            database_id=11,
        ),
        resource_type="location_label",
    )

    with pytest.raises(
        ApplyError,
        match="location_label UPDATE is not supported",
    ):
        prepare_metadata_plan(
            ResolvedPlan(metadata_items=(item,)),
        )


def test_metadata_preparation_rejects_wrong_values_type():
    item = replace(_site_item(), values=object())

    with pytest.raises(
        ApplyError,
        match="site requires ResolvedSiteValues",
    ):
        prepare_metadata_plan(
            ResolvedPlan(metadata_items=(item,)),
        )


def test_metadata_preparation_rejects_unknown_action():
    item = replace(_site_item(), action="delete")

    with pytest.raises(
        ApplyError,
        match="unsupported METADATA action",
    ):
        prepare_metadata_plan(
            ResolvedPlan(metadata_items=(item,)),
        )


@pytest.mark.parametrize("database_id", [0, -1, True, 1.5, "11"])
def test_metadata_preparation_rejects_invalid_reuse_id(database_id):
    item = _site_item(
        action=PlanAction.REUSE,
        database_id=database_id,
    )

    with pytest.raises(
        ApplyError,
        match="positive integer database_id",
    ):
        prepare_metadata_plan(
            ResolvedPlan(metadata_items=(item,)),
        )


def test_metadata_preparation_rejects_duplicate_plan_ids():
    first = _site_item()
    second = replace(
        first,
        values=ResolvedSiteValues(
            site_code="SITE_B",
            name="Another site",
        ),
    )

    with pytest.raises(
        ApplyError,
        match="duplicate METADATA plan_id",
    ):
        prepare_metadata_plan(
            ResolvedPlan(metadata_items=(first, second)),
        )


def test_metadata_preparation_rejects_duplicate_update_targets():
    first = _site_item(
        "updates.sites[0]",
        action=PlanAction.UPDATE,
        database_id=11,
    )
    second = replace(first, plan_id="updates.sites[1]")

    with pytest.raises(
        ApplyError,
        match="duplicate METADATA UPDATE target",
    ):
        prepare_metadata_plan(
            ResolvedPlan(metadata_items=(first, second)),
        )


def test_metadata_preparation_accepts_reuse_and_update_of_same_row():
    reused = _site_item(
        "sites[0]",
        action=PlanAction.REUSE,
        database_id=11,
    )
    updated = _site_item(
        "updates.sites[0]",
        action=PlanAction.UPDATE,
        database_id=11,
    )
    items = (reused, updated)

    prepared = prepare_metadata_plan(
        ResolvedPlan(metadata_items=items),
    )

    assert prepared.items == items
    assert prepared.requires_writes is True


