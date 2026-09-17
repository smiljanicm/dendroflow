import os
from dataclasses import replace
from uuid import uuid4

import pytest
from psycopg.errors import CheckViolation, UniqueViolation

from dendroflow.configuration.persistence import (
    ApplyError,
    ApplyErrorCode,
    ApplyStageStatus,
    ApplyStatus,
    apply_metadata_plan,
)
from dendroflow.configuration.plan import (
    FieldChange,
    PlanAction,
    PlannedRef,
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSiteValues,
)
from dendroflow.database import connect

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("DENDROFLOW_INTEGRATION") != "1",
        reason="Set DENDROFLOW_INTEGRATION=1 to run PostgreSQL integration tests",
    ),
]


@pytest.fixture
def site_codes():
    prefix = f"config_apply_{uuid4().hex}"
    codes = {}

    def code(label):
        return codes.setdefault(label, f"{prefix}_{label}")

    try:
        yield code
    finally:
        if codes:
            with connect("dendroflow_metadata") as connection:
                connection.execute(
                    """
                    UPDATE sites
                    SET parent_id = NULL
                    WHERE site_code = ANY(%s)
                    """,
                    (list(codes.values()),),
                )
                connection.execute(
                    """
                    DELETE FROM sites
                    WHERE site_code = ANY(%s)
                    """,
                    (list(codes.values()),),
                )


def seed_site(code, name):
    with connect("dendroflow_metadata") as connection:
        row = connection.execute(
            """
            INSERT INTO sites (site_code, name)
            VALUES (%s, %s)
            RETURNING site_id
            """,
            (code, name),
        ).fetchone()

    return row[0]


def read_sites(*codes):
    with connect("dendroflow_metadata") as connection:
        rows = connection.execute(
            """
            SELECT site_code, site_id, name, parent_id
            FROM sites
            WHERE site_code = ANY(%s)
            """,
            (list(codes),),
        ).fetchall()

    return {
        code: (database_id, name, parent_id)
        for code, database_id, name, parent_id in rows
    }


def create_site(plan_id, code, *, parent=None, latitude=None):
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="site",
        action=PlanAction.CREATE,
        values=ResolvedSiteValues(
            site_code=code,
            name=plan_id,
            parent=parent,
            latitude=latitude,
        ),
    )


def rename_site(plan_id, code, database_id, before, after):
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="site",
        action=PlanAction.UPDATE,
        database_id=database_id,
        values=ResolvedSiteValues(
            site_code=code,
            name=after,
        ),
        changes=(
            FieldChange(
                field="name",
                before=before,
                after=after,
            ),
        ),
    )


def test_mixed_plan_commits_and_preserves_result_order(site_codes):
    existing_code = site_codes("existing")
    parent_code = site_codes("parent")
    child_code = site_codes("child")
    existing_id = seed_site(existing_code, "Original")

    parent = create_site("parent", parent_code)
    child = create_site(
        "child",
        child_code,
        parent=PlannedRef("site", "parent"),
    )
    update = rename_site(
        "update",
        existing_code,
        existing_id,
        "Original",
        "Corrected",
    )
    reuse = replace(
        create_site("reuse", existing_code),
        action=PlanAction.REUSE,
        database_id=existing_id,
    )

    result = apply_metadata_plan(
        ResolvedPlan(
            metadata_items=(child, update, reuse, parent),
        )
    )

    assert result.status == ApplyStatus.SUCCESS
    assert result.metadata_status == ApplyStageStatus.COMMITTED
    assert result.raw_status == ApplyStageStatus.NOT_REQUIRED
    assert [item.plan_id for item in result.items] == [
        "child",
        "update",
        "reuse",
        "parent",
    ]
    assert [item.action for item in result.items] == [
        PlanAction.CREATE,
        PlanAction.UPDATE,
        PlanAction.REUSE,
        PlanAction.CREATE,
    ]

    ids = {
        item.plan_id: item.database_id
        for item in result.items
    }

    assert ids["update"] == existing_id
    assert ids["reuse"] == existing_id
    assert read_sites(existing_code, parent_code, child_code) == {
        existing_code: (existing_id, "Corrected", None),
        parent_code: (ids["parent"], "parent", None),
        child_code: (ids["child"], "child", ids["parent"]),
    }


def test_unique_key_is_released_before_create(site_codes):
    old_code = site_codes("old")
    new_code = site_codes("new")
    existing_id = seed_site(old_code, "Existing")

    claimant = create_site("claimant", old_code)
    release = ResolvedPlanItem(
        plan_id="release",
        resource_type="site",
        action=PlanAction.UPDATE,
        database_id=existing_id,
        values=ResolvedSiteValues(
            site_code=new_code,
            name="Existing",
        ),
        changes=(
            FieldChange(
                field="site_code",
                before=old_code,
                after=new_code,
                identity_change=True,
            ),
        ),
    )

    # Source order deliberately puts the claimant first.
    result = apply_metadata_plan(
        ResolvedPlan(metadata_items=(claimant, release)),
        confirm_identity_changes=True,
    )

    assert result.metadata_status == ApplyStageStatus.COMMITTED
    assert [item.plan_id for item in result.items] == [
        "claimant",
        "release",
    ]
    assert result.items[1].database_id == existing_id
    assert result.items[0].database_id != existing_id
    assert read_sites(old_code, new_code) == {
        old_code: (
            result.items[0].database_id,
            "claimant",
            None,
        ),
        new_code: (existing_id, "Existing", None),
    }


def test_stale_update_rolls_back_earlier_insert_and_update(site_codes):
    existing_code = site_codes("existing")
    stale_code = site_codes("stale")
    created_code = site_codes("created")

    existing_id = seed_site(existing_code, "Original")
    stale_id = seed_site(stale_code, "Actual database value")

    plan = ResolvedPlan(
        metadata_items=(
            create_site("created", created_code),
            rename_site(
                "valid-update",
                existing_code,
                existing_id,
                "Original",
                "Temporary change",
            ),
            rename_site(
                "stale-update",
                stale_code,
                stale_id,
                "Outdated plan value",
                "Requested change",
            ),
        ),
    )

    with pytest.raises(ApplyError) as caught:
        apply_metadata_plan(plan)

    assert caught.value.code == ApplyErrorCode.STALE_PLAN
    assert read_sites(
        existing_code,
        stale_code,
        created_code,
    ) == {
        existing_code: (existing_id, "Original", None),
        stale_code: (stale_id, "Actual database value", None),
    }


@pytest.mark.parametrize(
    ("failure_kind", "expected_error"),
    [
        ("unique", UniqueViolation),
        ("check", CheckViolation),
    ],
)
def test_database_error_rolls_back_earlier_writes(
    site_codes,
    failure_kind,
    expected_error,
):
    existing_code = site_codes("existing")
    occupied_code = site_codes("occupied")
    created_code = site_codes("created")
    invalid_code = site_codes("invalid")

    existing_id = seed_site(existing_code, "Original")
    occupied_id = seed_site(occupied_code, "Occupied")

    if failure_kind == "unique":
        failing_item = create_site("failing", occupied_code)
    else:
        failing_item = create_site(
            "failing",
            invalid_code,
            latitude=91.0,
        )

    plan = ResolvedPlan(
        metadata_items=(
            rename_site(
                "valid-update",
                existing_code,
                existing_id,
                "Original",
                "Temporary change",
            ),
            create_site("created", created_code),
            failing_item,
        ),
    )

    with pytest.raises(expected_error):
        apply_metadata_plan(plan)

    assert read_sites(
        existing_code,
        occupied_code,
        created_code,
        invalid_code,
    ) == {
        existing_code: (existing_id, "Original", None),
        occupied_code: (occupied_id, "Occupied", None),
    }
