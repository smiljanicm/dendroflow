from dataclasses import replace
from datetime import datetime, timezone

import pytest

from dendroflow import database
from dendroflow.configuration.persistence.models import (
    ApplyError,
    ApplyErrorCode,
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
)


@pytest.fixture(autouse=True)
def forbid_database_connections(monkeypatch):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("RAW preparation must not connect to a database")

    monkeypatch.setattr(database, "connect", unexpected_connection)


def file_item(plan_id="file"):
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="file",
        action=PlanAction.CREATE,
        values=ResolvedFileValues(
            filepath=f"/data/{plan_id}.csv",
            timestamp_timezone="UTC",
            timestamp_format="%Y-%m-%d %H:%M:%S",
            reader_config={"reader": "csv", "options": {}},
        ),
    )


def interface_item(plan_id="interface"):
    return ResolvedPlanItem(
        plan_id=plan_id,
        resource_type="interface",
        action=PlanAction.CREATE,
        values=ResolvedInterfaceValues(
            file=ExistingRef("file", 17),
            deployment=ExistingRef("deployment", 91),
            values_column=plan_id,
            timestamp_column="TIMESTAMP",
            unit="cm",
        ),
    )


def deployment_item(plan_id="deployment"):
    return ResolvedPlanItem(
        plan_id=plan_id,
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


def with_reference(item, field, reference):
    return replace(
        item,
        values=replace(item.values, **{field: reference}),
    )


def assert_invalid(plan, **kwargs):
    with pytest.raises(ApplyError) as caught:
        prepare_raw_plan(plan, **kwargs)

    assert caught.value.code == ApplyErrorCode.PLAN_NOT_APPLICABLE


def test_empty_plan_requires_no_writes():
    prepared = prepare_raw_plan(ResolvedPlan())

    assert prepared.items == ()
    assert prepared.execution_items == ()
    assert prepared.required_metadata_plan_ids == ()
    assert prepared.requires_writes is False


def test_reuse_only_plan_preserves_items_without_writes():
    items = (
        replace(
            file_item(),
            action=PlanAction.REUSE,
            database_id=17,
        ),
        replace(
            interface_item(),
            action=PlanAction.REUSE,
            database_id=101,
        ),
    )

    prepared = prepare_raw_plan(ResolvedPlan(raw_items=items))

    assert prepared.items == items
    assert prepared.execution_items == items
    assert prepared.required_metadata_plan_ids == ()
    assert prepared.requires_writes is False


def test_ordering_selects_earliest_ready_item():
    file = file_item()
    independent = file_item("independent")
    first = with_reference(
        interface_item("first"),
        "file",
        PlannedRef("file", file.plan_id),
    )
    second = with_reference(
        interface_item("second"),
        "file",
        PlannedRef("file", file.plan_id),
    )
    original = (first, independent, file, second)

    prepared = prepare_raw_plan(
        ResolvedPlan(raw_items=original)
    )

    assert prepared.items == original
    assert prepared.execution_items == (
        independent,
        file,
        first,
        second,
    )
    assert prepared.required_metadata_plan_ids == ()
    assert prepared.requires_writes is True


def test_plan_errors_are_rejected():
    plan = ResolvedPlan(
        raw_items=(file_item(),),
        errors=(
            PlanError(
                code=PlanErrorCode.CONFLICT,
                resource_type="file",
                source_path="files[0]",
                message="Conflicting file settings",
            ),
        ),
    )

    assert_invalid(plan)


@pytest.mark.parametrize("confirmed", [False, True])
def test_confirmation_is_forwarded_to_preflight(confirmed):
    item = replace(file_item(), confirmation_required=True)
    plan = ResolvedPlan(raw_items=(item,))

    if confirmed:
        prepared = prepare_raw_plan(
            plan,
            confirm_identity_changes=True,
        )
        assert prepared.items == (item,)
    else:
        with pytest.raises(ApplyError) as caught:
            prepare_raw_plan(plan)

        assert caught.value.code == ApplyErrorCode.CONFIRMATION_REQUIRED


def test_standalone_preparation_rejects_metadata_items():
    assert_invalid(
        ResolvedPlan(
            metadata_items=(deployment_item(),),
            raw_items=(file_item(),),
        )
    )


def test_combined_preparation_records_shared_deployment_dependency():
    deployment = deployment_item()
    file = file_item()
    first = with_reference(
        interface_item("first"),
        "deployment",
        PlannedRef("deployment", deployment.plan_id),
    )
    first = with_reference(
        first,
        "file",
        PlannedRef("file", file.plan_id),
    )
    second = replace(first, plan_id="second")
    raw_items = (first, file, second)

    prepared = prepare_raw_plan(
        ResolvedPlan(
            metadata_items=(deployment,),
            raw_items=raw_items,
        ),
        allow_metadata_dependencies=True,
    )

    assert prepared.items == raw_items
    assert prepared.execution_items == (file, first, second)
    assert prepared.required_metadata_plan_ids == ("deployment",)


@pytest.mark.parametrize("location", ["raw", "cross-stage", "metadata"])
def test_duplicate_plan_ids_are_rejected(location):
    if location == "raw":
        plan = ResolvedPlan(
            raw_items=(file_item(), file_item()),
        )
    elif location == "cross-stage":
        plan = ResolvedPlan(
            metadata_items=(deployment_item("shared"),),
            raw_items=(file_item("shared"),),
        )
    else:
        plan = ResolvedPlan(
            metadata_items=(
                deployment_item(),
                deployment_item(),
            ),
            raw_items=(file_item(),),
        )

    assert_invalid(plan, allow_metadata_dependencies=True)


@pytest.mark.parametrize(
    "case",
    [
        "unsupported-resource",
        "string-action",
        "update",
        "wrong-file-values",
        "wrong-interface-values",
        "boolean-id",
        "zero-id",
        "float-id",
        "invalid-reader-config",
    ],
)
def test_invalid_raw_items_are_rejected(case):
    item = file_item()

    if case == "unsupported-resource":
        item = replace(item, resource_type="site")
    elif case == "string-action":
        item = replace(item, action="create")
    elif case == "update":
        item = replace(
            item,
            action=PlanAction.UPDATE,
            database_id=17,
            changes=(
                FieldChange(
                    field="timestamp_timezone",
                    before="Europe/Berlin",
                    after="UTC",
                ),
            ),
        )
    elif case == "wrong-file-values":
        item = replace(item, values=interface_item().values)
    elif case == "wrong-interface-values":
        item = replace(interface_item(), values=item.values)
    elif case in {"boolean-id", "zero-id", "float-id"}:
        database_id = {
            "boolean-id": True,
            "zero-id": 0,
            "float-id": 17.0,
        }[case]
        item = replace(
            item,
            action=PlanAction.REUSE,
            database_id=database_id,
        )
    else:
        item = replace(
            item,
            values=replace(item.values, reader_config=[]),
        )

    assert_invalid(ResolvedPlan(raw_items=(item,)))


@pytest.mark.parametrize("field", ["file", "deployment"])
@pytest.mark.parametrize(
    "case",
    ["missing", "wrong-type", "boolean-id", "missing-target"],
)
def test_invalid_interface_references_are_rejected(field, case):
    if case == "missing":
        reference = None
    elif case == "wrong-type":
        reference = ExistingRef("site", 17)
    elif case == "boolean-id":
        reference = ExistingRef(field, True)
    else:
        reference = PlannedRef(field, "missing")

    item = with_reference(interface_item(), field, reference)

    assert_invalid(
        ResolvedPlan(raw_items=(item,)),
        allow_metadata_dependencies=True,
    )


@pytest.mark.parametrize("target_kind", ["reuse", "wrong-resource"])
def test_planned_file_requires_matching_file_create(target_kind):
    if target_kind == "reuse":
        target = replace(
            file_item("target"),
            action=PlanAction.REUSE,
            database_id=17,
        )
    else:
        target = interface_item("target")

    item = with_reference(
        interface_item(),
        "file",
        PlannedRef("file", "target"),
    )

    assert_invalid(ResolvedPlan(raw_items=(item, target)))


@pytest.mark.parametrize("field", ["file", "deployment"])
def test_reuse_cannot_depend_on_planned_resources(field):
    item = with_reference(
        interface_item(),
        field,
        PlannedRef(field, field),
    )
    item = replace(
        item,
        action=PlanAction.REUSE,
        database_id=101,
    )

    assert_invalid(
        ResolvedPlan(
            metadata_items=(deployment_item(),),
            raw_items=(file_item(), item),
        ),
        allow_metadata_dependencies=True,
    )


@pytest.mark.parametrize(
    "case",
    ["reuse", "wrong-values", "wrong-resource", "string-action"],
)
def test_planned_deployment_requires_matching_metadata_create(case):
    target = deployment_item()

    if case == "reuse":
        target = replace(
            target,
            action=PlanAction.REUSE,
            database_id=91,
        )
    elif case == "wrong-values":
        target = replace(target, values=object())
    elif case == "wrong-resource":
        target = replace(target, resource_type="site")
    else:
        target = replace(target, action="create")

    item = with_reference(
        interface_item(),
        "deployment",
        PlannedRef("deployment", target.plan_id),
    )

    assert_invalid(
        ResolvedPlan(
            metadata_items=(target,),
            raw_items=(item,),
        ),
        allow_metadata_dependencies=True,
    )
