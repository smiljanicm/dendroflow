from dataclasses import replace
from datetime import datetime, timezone

import psycopg
import pytest

from dendroflow.cli.reporting import format_apply_result, format_plan
from dendroflow.configuration.persistence.models import (
    ApplyExecutionError,
    ApplyItemResult,
    ApplyResult,
    ApplyStageStatus,
    ApplyStatus,
)
from dendroflow.configuration.plan import (
    ExistingRef,
    FieldChange,
    NaturalIdentity,
    PlanAction,
    PlanError,
    PlanErrorCode,
    PlannedRef,
    PlanWarning,
    ResolvedDeploymentValues,
    ResolvedFileValues,
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSiteValues,
)


@pytest.fixture(autouse=True)
def block_database_access(monkeypatch):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("Reporting must not connect to PostgreSQL")

    monkeypatch.setattr(psycopg, "connect", unexpected_connection)


def site_item():
    return ResolvedPlanItem(
        plan_id="site:station",
        resource_type="site",
        action=PlanAction.CREATE,
        values=ResolvedSiteValues(site_code="station", name="Station"),
        source_path="sites[0]",
    )


def test_empty_plan_report():
    assert format_plan(ResolvedPlan()) == (
        "Configuration plan\n"
        "Total: CREATE=0, REUSE=0, UPDATE=0\n"
        "Errors: 0; warnings: 0\n"
        "Confirmation required: no\n"
        "\n"
        "METADATA: CREATE=0, REUSE=0, UPDATE=0\n"
        "  (no items)\n"
        "\n"
        "RAW: CREATE=0, REUSE=0, UPDATE=0\n"
        "  (no items)"
    )


def test_plan_groups_stages_counts_actions_and_preserves_order():
    create = site_item()
    reuse = replace(
        create,
        plan_id="site:existing",
        action=PlanAction.REUSE,
        database_id=7,
    )
    update = replace(
        reuse,
        plan_id="site:correction",
        database_id=8,
        changes=(FieldChange("name", "Old", "Station"),),
        action=PlanAction.UPDATE,
    )
    file = ResolvedPlanItem(
        plan_id="file:logger",
        resource_type="file",
        action=PlanAction.CREATE,
        values=ResolvedFileValues("/data/logger.csv", "UTC", "%Y", {}),
    )
    report = format_plan(
        ResolvedPlan(metadata_items=(reuse, create, update), raw_items=(file,))
    )

    assert "Total: CREATE=2, REUSE=1, UPDATE=1" in report
    assert "METADATA: CREATE=1, REUSE=1, UPDATE=1" in report
    assert "RAW: CREATE=1, REUSE=0, UPDATE=0" in report
    headings = [
        "REUSE site 'site:existing' (database_id=7)",
        "CREATE site 'site:station'",
        "UPDATE site 'site:correction' (database_id=8)",
        "CREATE file 'file:logger'",
    ]
    positions = [report.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "source: 'sites[0]'" in report
    assert "site_code: 'station'" in report
    assert "filepath: '/data/logger.csv'" in report


@pytest.mark.parametrize("identity_change", [False, True])
def test_update_report_marks_confirmation_and_identity_changes(identity_change):
    item = replace(
        site_item(),
        action=PlanAction.UPDATE,
        database_id=7,
        changes=(
            FieldChange("site_code", "old", "station", identity_change),
        ),
    )

    report = format_plan(ResolvedPlan(metadata_items=(item,)))

    assert "site_code: 'old' -> 'station'" in report
    assert ("[identity change]" in report) is identity_change
    expected = "yes" if identity_change else "no"
    assert f"Confirmation required: {expected}" in report


def test_explicit_confirmation_is_reported_without_identity_marker():
    item = replace(site_item(), confirmation_required=True)

    report = format_plan(ResolvedPlan(metadata_items=(item,)))

    assert "Confirmation required: yes" in report
    assert "    confirmation required" in report
    assert "[identity change]" not in report


def test_natural_identity_is_reported():
    item = replace(
        site_item(),
        identity=NaturalIdentity((("site_code", "station"),)),
    )

    report = format_plan(ResolvedPlan(metadata_items=(item,)))

    assert "identity: site_code='station'" in report


def test_relationships_timestamps_and_null_changes_are_readable():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 2, 1, tzinfo=timezone.utc)
    item = ResolvedPlanItem(
        plan_id="deployment:temperature",
        resource_type="deployment",
        action=PlanAction.UPDATE,
        database_id=12,
        values=ResolvedDeploymentValues(
            sensor=ExistingRef("sensor", 7),
            location=PlannedRef("location", "location:new"),
            variable=ExistingRef("variable", 3),
            valid_from=start,
            valid_to=None,
        ),
        changes=(FieldChange("valid_to", end, None),),
    )

    report = format_plan(ResolvedPlan(metadata_items=(item,)))

    assert "sensor: existing sensor #7" in report
    assert "location: planned location 'location:new'" in report
    assert "valid_from: 2026-01-01T00:00:00+00:00" in report
    assert "valid_to: 2026-02-01T00:00:00+00:00 -> null" in report


def test_reader_options_are_deterministic_without_mutation(capsys):
    options = {"skiprows": [0, 2], "header": None, "enabled": False}
    values = ResolvedFileValues(
        "/data/logger.csv",
        "UTC",
        "%Y",
        {"reader": "csv", "options": options},
    )
    item = ResolvedPlanItem("file:logger", "file", PlanAction.CREATE, values)
    plan = ResolvedPlan(raw_items=(item,))
    reordered = replace(
        item,
        values=replace(
            values,
            reader_config={
                "options": dict(reversed(list(options.items()))),
                "reader": "csv",
            },
        ),
    )

    report = format_plan(plan)

    assert report == format_plan(ResolvedPlan(raw_items=(reordered,)))
    assert "'enabled': false, 'header': null, 'skiprows': [0, 2]" in report
    assert list(options) == ["skiprows", "header", "enabled"]
    assert options["skiprows"] == [0, 2]
    assert plan.raw_items == (item,)
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_multiline_values_are_escaped():
    item = replace(
        site_item(),
        values=ResolvedSiteValues("station", "Station\nsecond line"),
    )

    report = format_plan(ResolvedPlan(metadata_items=(item,)))

    assert "name: 'Station\\nsecond line'" in report


def test_plan_diagnostics_include_paths_and_candidates():
    plan = ResolvedPlan(
        errors=(
            PlanError(
                PlanErrorCode.AMBIGUOUS,
                "sensor",
                "references.sensors.logger",
                "More than one sensor matches",
                (7, 9),
            ),
        ),
        warnings=(PlanWarning("example", "sites[0]", "Review this site"),),
    )

    report = format_plan(plan)

    assert "Errors: 1; warnings: 1" in report
    assert "example at 'sites[0]': Review this site" in report
    assert (
        "AMBIGUOUS sensor at 'references.sensors.logger': "
        "More than one sensor matches"
    ) in report
    assert "candidate IDs: 7, 9" in report
    assert "ready to apply" not in report.lower()


@pytest.mark.parametrize(
    ("status", "metadata", "raw"),
    [
        ("success", "committed", "committed"),
        ("success", "not_required", "not_required"),
        ("failed", "failed", "not_started"),
        ("partial", "committed", "failed"),
        ("partial", "committed", "not_started"),
        ("unknown", "unknown", "not_started"),
        ("unknown", "committed", "unknown"),
    ],
)
def test_apply_report_preserves_stage_outcomes(status, metadata, raw):
    result = ApplyResult(
        ApplyStatus(status),
        ApplyStageStatus(metadata),
        ApplyStageStatus(raw),
    )

    report = format_apply_result(result)

    assert f"Database outcome: {status.upper()}" in report
    assert f"METADATA: {metadata.upper()}" in report
    assert f"RAW: {raw.upper()}" in report
    assert "(none reported)" in report
    if status == "partial":
        assert "METADATA committed; required RAW work did not complete." in report
    if status == "unknown":
        assert "Missing item results do not prove rollback." in report


def test_apply_report_preserves_item_order_and_reuse_semantics(capsys):
    items = (
        ApplyItemResult("site:existing", "site", PlanAction.REUSE, 7),
        ApplyItemResult("site:new", "site", PlanAction.CREATE, 8),
    )
    result = ApplyResult(
        ApplyStatus.SUCCESS,
        ApplyStageStatus.COMMITTED,
        ApplyStageStatus.NOT_REQUIRED,
        items,
    )

    report = format_apply_result(result)

    assert "committed writes and completed REUSE operations" in report
    assert report.index("REUSE site 'site:existing'") < report.index(
        "CREATE site 'site:new'"
    )
    assert "(database_id=7)" in report
    assert "(database_id=8)" in report
    assert result.items == items
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_cleanup_error_can_report_successful_database_outcome():
    result = ApplyResult(
        ApplyStatus.SUCCESS,
        ApplyStageStatus.COMMITTED,
        ApplyStageStatus.NOT_REQUIRED,
    )
    error = ApplyExecutionError("Connection cleanup failed", result=result)

    report = format_apply_result(error.result)

    assert "Database outcome: SUCCESS" in report
    assert "METADATA: COMMITTED" in report
    assert "command succeeded" not in report.lower()
    assert "rolled back" not in report.lower()

