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
    ResolvedDeploymentValues,
    ResolvedPlan,
    ResolvedPlanItem,
)


@pytest.fixture(autouse=True)
def forbid_database_connections(monkeypatch):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("deployment ordering must not open a connection")

    monkeypatch.setattr(database, "connect", unexpected_connection)


def _state(
    *,
    sensor_id=11,
    variable_id=31,
    location_id=21,
    start_month=1,
    end_month=None,
):
    return ResolvedDeploymentValues(
        sensor=ExistingRef("sensor", sensor_id),
        location=ExistingRef("location", location_id),
        variable=ExistingRef("variable", variable_id),
        valid_from=datetime(
            2025, start_month, 1, tzinfo=timezone.utc
        ),
        valid_to=(
            None
            if end_month is None
            else datetime(2025, end_month, 1, tzinfo=timezone.utc)
        ),
    )


def _create(plan_id, values):
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="deployment",
        action=PlanAction.CREATE,
        values=values,
    )


def _update(plan_id, database_id, before, after):
    fields = (
        "sensor",
        "location",
        "variable",
        "valid_from",
        "valid_to",
    )

    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="deployment",
        action=PlanAction.UPDATE,
        database_id=database_id,
        values=after,
        changes=tuple(
            FieldChange(
                field=field,
                before=getattr(before, field),
                after=getattr(after, field),
                identity_change=field != "valid_to",
            )
            for field in fields
            if getattr(before, field) != getattr(after, field)
        ),
    )


def _prepare(*items):
    return prepare_metadata_plan(
        ResolvedPlan(metadata_items=items),
        confirm_identity_changes=True,
    )


@pytest.mark.parametrize(
    "successor_action",
    [PlanAction.CREATE, PlanAction.UPDATE],
    ids=["create-successor", "update-successor"],
)
@pytest.mark.parametrize(
    "reverse_order",
    [False, True],
    ids=["closing-first", "successor-first"],
)
def test_deployment_closes_before_successor(
    successor_action,
    reverse_order,
):
    old_end = 6 if successor_action == PlanAction.UPDATE else None

    closing = _update(
        "closing",
        41,
        _state(end_month=old_end),
        _state(end_month=3),
    )

    successor_state = _state(start_month=3, location_id=22)

    if successor_action == PlanAction.CREATE:
        successor = _create("successor", successor_state)
    else:
        successor = _update(
            "successor",
            42,
            _state(start_month=6, location_id=22),
            successor_state,
        )

    items = (closing, successor)
    if reverse_order:
        items = tuple(reversed(items))

    prepared = _prepare(*items)

    assert prepared.items == items
    assert prepared.execution_items == (closing, successor)


@pytest.mark.parametrize("field", ["sensor", "variable"])
def test_deployment_relationship_change_releases_old_interval(field):
    before = _state()
    after = replace(
        before,
        **{field: ExistingRef(field, 99)},
    )

    moved = _update("moved", 41, before, after)
    replacement = _create("replacement", before)

    prepared = _prepare(replacement, moved)

    assert prepared.execution_items == (moved, replacement)


def test_deployment_start_change_releases_earlier_interval():
    moved = _update(
        "moved",
        41,
        _state(),
        _state(start_month=6),
    )
    replacement = _create(
        "replacement",
        _state(end_month=6),
    )

    prepared = _prepare(replacement, moved)

    assert prepared.execution_items == (moved, replacement)


def test_deployment_old_interval_adjacency_adds_no_dependency():
    shortened = _update(
        "shortened",
        41,
        _state(end_month=3),
        _state(end_month=2),
    )
    later = _create("later", _state(start_month=3))

    prepared = _prepare(later, shortened)

    assert prepared.execution_items == (later, shortened)


@pytest.mark.parametrize(
    ("sensor_id", "variable_id"),
    [(12, 31), (11, 32)],
    ids=["different-sensor", "different-variable"],
)
def test_deployment_different_exclusion_key_adds_no_dependency(
    sensor_id,
    variable_id,
):
    closing = _update(
        "closing",
        41,
        _state(),
        _state(end_month=3),
    )
    independent = _create(
        "independent",
        _state(
            sensor_id=sensor_id,
            variable_id=variable_id,
            start_month=2,
        ),
    )

    prepared = _prepare(independent, closing)

    assert prepared.execution_items == (independent, closing)


@pytest.mark.parametrize("location_id", [21, 22])
def test_deployment_ordering_rejects_overlapping_final_states(location_id):
    closing = _update(
        "closing",
        41,
        _state(),
        _state(end_month=4),
    )
    successor = _create(
        "successor",
        _state(start_month=3, location_id=location_id),
    )

    with pytest.raises(
        ApplyError,
        match="overlapping final deployment states",
    ) as caught:
        _prepare(successor, closing)

    assert caught.value.code == ApplyErrorCode.PLAN_NOT_APPLICABLE


def test_deployment_interval_swap_is_rejected_as_cycle():
    early = _state(end_month=3)
    late = _state(start_month=3, end_month=6)

    first = _update("first", 41, early, late)
    second = _update("second", 42, late, early)

    with pytest.raises(ApplyError, match="dependency cycle") as caught:
        _prepare(first, second)

    assert caught.value.code == ApplyErrorCode.PLAN_NOT_APPLICABLE
    assert "first" in str(caught.value)
    assert "second" in str(caught.value)


def test_deployment_reuse_snapshot_does_not_block_handoff():
    before = _state()
    reused = replace(
        _create("reused", before),
        action=PlanAction.REUSE,
        database_id=41,
    )
    closing = _update(
        "closing",
        41,
        before,
        _state(end_month=3),
    )
    successor = _create(
        "successor",
        _state(start_month=3),
    )

    prepared = _prepare(successor, reused, closing)

    assert prepared.items == (successor, reused, closing)
    assert prepared.execution_items == (reused, closing, successor)
