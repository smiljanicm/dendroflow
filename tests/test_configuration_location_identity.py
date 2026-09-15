from dataclasses import replace

import pytest

from dendroflow.configuration.plan import (
    ExistingRef,
    FieldChange,
    NaturalIdentity,
    PlanAction,
    PlannedRef,
    ResolvedLocationValues,
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSiteValues,
)
from dendroflow.configuration.resolution.consistency import (
    collect_plan_consistency_errors,
)


def location(plan_id, site, label, database_id=None, action=PlanAction.CREATE):
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="location",
        action=action,
        database_id=database_id,
        values=ResolvedLocationValues(
            site=site,
            location_type=ExistingRef("location_type", 1),
            latitude=None,
            longitude=None,
            height_above_ground=None,
            azimuth=None,
        ),
        identity=NaturalIdentity((("site", site), ("initial_label", label))),
        changes=(FieldChange("site", ExistingRef("site", 9), site, True),)
        if action == PlanAction.UPDATE
        else (),
        source_path=plan_id,
    )


def test_natural_identity_requires_components():
    with pytest.raises(ValueError, match="at least one component"):
        NaturalIdentity(())


@pytest.mark.parametrize("planned_site", [False, True])
def test_distinct_locations_with_same_final_identity_conflict(planned_site):
    site = PlannedRef("site", "sites[0]") if planned_site else ExistingRef("site", 1)
    parents = (
        (
            ResolvedPlanItem(
                plan_id="sites[0]",
                resource_type="site",
                action=PlanAction.CREATE,
                values=ResolvedSiteValues(site_code="A", name="A"),
            ),
        )
        if planned_site
        else ()
    )
    first = location("locations[0]", site, "tree_001")
    second = location("locations[1]", site, "tree_001")
    errors = collect_plan_consistency_errors(
        ResolvedPlan(
            metadata_items=parents + (first, second),
        )
    )
    assert len(errors) == 1
    assert errors[0].source_path == "locations[1]"
    assert "final identity" in errors[0].message


def test_same_label_at_different_sites_is_distinct():
    items = tuple(
        location(f"locations[{i}]", ExistingRef("site", i + 1), "tree")
        for i in range(2)
    )
    assert collect_plan_consistency_errors(ResolvedPlan(metadata_items=items)) == ()


def test_update_releases_reused_identity_and_conflicts_at_destination():
    old_site, new_site = ExistingRef("site", 1), ExistingRef("site", 2)
    reused = location("locations[0]", old_site, "tree", 7, PlanAction.REUSE)
    updated = location("updates.locations[0]", new_site, "tree", 7, PlanAction.UPDATE)
    created = location("locations[1]", old_site, "tree")
    assert (
        collect_plan_consistency_errors(
            ResolvedPlan(
                metadata_items=(reused, updated, created),
            )
        )
        == ()
    )
    destination = location("locations[2]", new_site, "tree", 8, PlanAction.REUSE)
    errors = collect_plan_consistency_errors(
        ResolvedPlan(
            metadata_items=(destination, updated),
        )
    )
    assert len(errors) == 1
    assert errors[0].source_path == updated.source_path


def test_component_order_does_not_change_identity():
    first = location("locations[0]", ExistingRef("site", 1), "tree")
    second = replace(
        first,
        plan_id="locations[1]",
        identity=NaturalIdentity(
            tuple(reversed(first.identity.components)),
        ),
    )
    assert (
        len(
            collect_plan_consistency_errors(
                ResolvedPlan(
                    metadata_items=(first, second),
                )
            )
        )
        == 1
    )
