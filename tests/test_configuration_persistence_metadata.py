import pytest

from dendroflow.configuration.persistence.context import (
    ApplyContext,
)
from dendroflow.configuration.persistence.metadata import (
    create_metadata_item,
)
from dendroflow.configuration.plan import (
    FieldChange,
    PlanAction,
    ResolvedPlanItem,
    ResolvedSiteValues,
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

