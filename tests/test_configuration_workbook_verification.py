import pytest

from dendroflow.configuration.plan import (
    ExistingRef,
    FieldChange,
    PlanAction,
    PlanBinding,
    PlanError,
    PlanErrorCode,
    PlannedRef,
    ResolvedPlan,
    ResolvedPlanItem,
)
from dendroflow.configuration.workbook import verification
from dendroflow.configuration.workbook.configuration import generate_configuration
from dendroflow.configuration.workbook.matching import match_workbook
from dendroflow.configuration.workbook.schema import RESOURCE_SHEETS
from dendroflow.configuration.workbook.verification import (
    WorkbookPlanVerificationError,
    verify_generated_configuration,
)

from . import test_configuration_workbook_validation as helpers


@pytest.fixture
def source():
    return helpers.source.__wrapped__()


def generated(parsed, source):
    return generate_configuration(match_workbook(parsed, source))


def reference_bindings(result):
    bindings = []
    for spec in RESOURCE_SHEETS:
        if spec.name not in result.selectors.selectors:
            continue
        section = getattr(result.config.references, spec.name)
        selectors = {
            selector.alias: selector
            for selector in result.selectors.selectors.get(spec.name, {}).values()
        }
        for alias in section:
            selector = selectors[alias]
            bindings.append(
                PlanBinding(
                    spec.name,
                    alias,
                    ExistingRef(spec.resource_type, selector.database_id),
                )
            )
    return bindings


def install_plan(monkeypatch, plan):
    def resolve(config):
        assert config is not None
        return plan

    monkeypatch.setattr(verification, "resolve_config", resolve)


def test_unchanged_workbook_resolves_to_reference_bindings_and_no_operations(
    monkeypatch, source,
):
    result = generated(helpers.parsed_export(source), source)
    install_plan(monkeypatch, ResolvedPlan(bindings=tuple(reference_bindings(result))))

    verified = verify_generated_configuration(result)

    assert verified.serialized.config == result.config
    assert verified.plan.items == ()


def test_supported_update_must_target_original_id_and_match_field_change(
    monkeypatch, source,
):
    parsed = helpers.parsed_export(source)
    parsed.frames["sites"].at[1, "name"] = "Renamed North"
    result = generated(parsed, source)
    before = source["sites"].iloc[1]["name"]
    item = ResolvedPlanItem(
        plan_id="updates.sites[0]",
        resource_type="site",
        action=PlanAction.UPDATE,
        values=None,
        database_id=2,
        changes=(FieldChange("name", before, "Renamed North"),),
        source_path="updates.sites[0]",
    )
    plan = ResolvedPlan(
        metadata_items=(item,),
        bindings=tuple(reference_bindings(result)),
    )
    install_plan(monkeypatch, plan)

    verified = verify_generated_configuration(result)

    assert verified.plan.metadata_items[0].database_id == 2


def test_relationship_update_is_verified_against_resolved_target_alias(
    monkeypatch, source,
):
    parsed = helpers.parsed_export(source)
    model = parsed.frames["sensor_models"].iloc[0].to_dict()
    model.update(sensor_model_id=None, ref="new_model", model="New Model")
    helpers.add_row(parsed, "sensor_models", model)
    parsed.frames["sensors"].at[0, "sensor_model"] = "new_model"
    result = generated(parsed, source)
    update = ResolvedPlanItem(
        plan_id="updates.sensors[0]",
        resource_type="sensor",
        action=PlanAction.UPDATE,
        values=None,
        database_id=50,
        changes=(
            FieldChange(
                "sensor_model",
                ExistingRef("sensor_model", 40),
                PlannedRef("sensor_model", "sensor_models[0]"),
                identity_change=True,
            ),
        ),
        source_path="updates.sensors[0]",
    )
    declaration = ResolvedPlanItem(
        plan_id="sensor_models[0]",
        resource_type="sensor_model",
        action=PlanAction.CREATE,
        values=None,
        source_path="sensor_models[0]",
    )
    bindings = reference_bindings(result) + [
        PlanBinding("sensor_models", "new_model", PlannedRef("sensor_model", "sensor_models[0]")),
    ]
    install_plan(
        monkeypatch,
        ResolvedPlan(metadata_items=(declaration, update), bindings=tuple(bindings)),
    )

    verified = verify_generated_configuration(result)

    assert verified.plan.metadata_items == (declaration, update)


def test_new_declaration_must_bind_to_its_resolved_plan_item(monkeypatch, source):
    parsed = helpers.parsed_export(source)
    site = parsed.frames["sites"].iloc[1].to_dict()
    site.update(site_id=None, ref="new_site", site_code="new", name="New Site")
    helpers.add_row(parsed, "sites", site)
    result = generated(parsed, source)
    item = ResolvedPlanItem(
        plan_id="sites[0]",
        resource_type="site",
        action=PlanAction.CREATE,
        values=None,
        source_path="sites[0]",
    )
    plan = ResolvedPlan(
        metadata_items=(item,),
        bindings=tuple(reference_bindings(result))
        + (PlanBinding("sites", "new_site", PlannedRef("site", "sites[0]")),),
    )
    install_plan(monkeypatch, plan)

    assert verify_generated_configuration(result).plan.metadata_items == (item,)


def test_new_interface_for_existing_file_must_reuse_the_matched_file_id(
    monkeypatch, source,
):
    parsed = helpers.parsed_export(source)
    interface = parsed.frames["interfaces"].iloc[0].to_dict()
    interface.update(interface_id=None, ref="new_interface", values_column="new_column")
    helpers.add_row(parsed, "interfaces", interface)
    result = generated(parsed, source)
    file_item = ResolvedPlanItem(
        plan_id="files[0]",
        resource_type="file",
        action=PlanAction.REUSE,
        values=None,
        database_id=90,
        source_path="files[0]",
    )
    interface_item = ResolvedPlanItem(
        plan_id="files[0].interfaces[0]",
        resource_type="interface",
        action=PlanAction.CREATE,
        values=None,
        source_path="files[0].interfaces[0]",
    )
    plan = ResolvedPlan(
        raw_items=(file_item, interface_item),
        bindings=tuple(reference_bindings(result))
        + (PlanBinding("files", "file_90", ExistingRef("file", 90)),),
    )
    install_plan(monkeypatch, plan)

    assert verify_generated_configuration(result).plan.raw_items == (file_item, interface_item)


def test_misdirected_reference_binding_blocks_verification(monkeypatch, source):
    result = generated(helpers.parsed_export(source), source)
    bindings = reference_bindings(result)
    bindings[0] = PlanBinding(bindings[0].resource_type, bindings[0].alias,
                              ExistingRef(bindings[0].resource.resource_type, 999))
    install_plan(monkeypatch, ResolvedPlan(bindings=tuple(bindings)))

    with pytest.raises(WorkbookPlanVerificationError, match="expected ExistingRef"):
        verify_generated_configuration(result)


def test_mismatched_update_target_is_rejected(monkeypatch, source):
    parsed = helpers.parsed_export(source)
    parsed.frames["sites"].at[1, "name"] = "Renamed North"
    result = generated(parsed, source)
    item = ResolvedPlanItem(
        plan_id="updates.sites[0]",
        resource_type="site",
        action=PlanAction.UPDATE,
        values=None,
        database_id=3,
        changes=(FieldChange("name", source["sites"].iloc[1]["name"], "Renamed North"),),
        source_path="updates.sites[0]",
    )
    install_plan(
        monkeypatch,
        ResolvedPlan(metadata_items=(item,), bindings=tuple(reference_bindings(result))),
    )

    with pytest.raises(WorkbookPlanVerificationError, match="expected 2"):
        verify_generated_configuration(result)


def test_resolver_errors_are_reported_and_plan_is_retained(monkeypatch, source):
    result = generated(helpers.parsed_export(source), source)
    error = PlanError(
        PlanErrorCode.AMBIGUOUS,
        "site",
        "sites[0]",
        "site lookup was ambiguous",
        (2, 3),
    )
    plan = ResolvedPlan(errors=(error,), bindings=tuple(reference_bindings(result)))
    install_plan(monkeypatch, plan)

    with pytest.raises(WorkbookPlanVerificationError, match="site lookup was ambiguous") as caught:
        verify_generated_configuration(result)

    assert caught.value.plan is plan
