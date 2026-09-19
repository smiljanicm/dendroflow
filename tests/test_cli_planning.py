import runpy
import sys
from dataclasses import replace

import psycopg
import pytest

from dendroflow.cli import configuration
from dendroflow.cli.main import main
from dendroflow.configuration import metadata
from dendroflow.configuration.metadata import MetadataRow
from dendroflow.configuration.plan import (
    FieldChange,
    PlanAction,
    PlanError,
    PlanErrorCode,
    PlanWarning,
    ResolvedFileValues,
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSiteValues,
)


@pytest.fixture(autouse=True)
def block_database_access(monkeypatch):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("Tests must not open PostgreSQL connections")

    monkeypatch.setattr(psycopg, "connect", unexpected_connection)


def write_config(tmp_path, content="{}"):
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def use_plan(monkeypatch, resolved):
    monkeypatch.setattr(configuration, "resolve_config", lambda config: resolved)


@pytest.mark.parametrize(
    ("existing_name", "expected_code", "expected_text"),
    [
        (None, 0, "CREATE site 'sites[0]'"),
        ("Station", 0, "REUSE site 'sites[0]' (database_id=7)"),
        ("Different station", 2, "CONFLICT"),
    ],
)
def test_plan_uses_real_resolution_and_preparation(
    existing_name,
    expected_code,
    expected_text,
    monkeypatch,
    tmp_path,
    capsys,
):
    lookups = []

    def find_site(site_code):
        lookups.append(site_code)
        if existing_name is None:
            return None
        return MetadataRow(
            database_id=7,
            values={
                "site_code": "station",
                "name": existing_name,
                "description": None,
                "latitude": None,
                "longitude": None,
                "parent_id": None,
            },
        )

    monkeypatch.setattr(metadata, "find_site", find_site)
    path = write_config(
        tmp_path,
        "sites:\n  - site_code: station\n    name: Station\n",
    )

    assert main(["config", "plan", str(path)]) == expected_code
    assert lookups == ["station"]
    captured = capsys.readouterr()
    assert expected_text in captured.out
    if expected_code == 0:
        assert "Preparation checks passed. No changes were written." in captured.out
        assert captured.err == ""
    else:
        assert "Planning blocked:" in captured.err
        assert "Preparation checks passed" not in captured.out


@pytest.mark.parametrize(
    "content",
    [
        "sites: [",
        "sites:\n  - site_code: station\n",
        "variables:\n  - variable: temperature\n  - variable: temperature\n",
    ],
)
def test_invalid_input_stops_before_resolution(
    content,
    monkeypatch,
    tmp_path,
    capsys,
):
    def unexpected_resolution(config):
        pytest.fail("Invalid input must not reach resolution")

    monkeypatch.setattr(configuration, "resolve_config", unexpected_resolution)
    path = write_config(tmp_path, content)

    assert main(["config", "plan", str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Configuration validation failed:" in captured.err


def test_missing_file_reports_input_error(tmp_path, capsys):
    path = tmp_path / "missing.yaml"

    assert main(["config", "plan", str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unable to read configuration file" in captured.err


def test_empty_plan_succeeds_without_connections(tmp_path, capsys):
    path = write_config(tmp_path)

    assert main(["config", "plan", str(path)]) == 0
    captured = capsys.readouterr()
    assert "Total: CREATE=0, REUSE=0, UPDATE=0" in captured.out
    assert "Preparation checks passed" in captured.out
    assert captured.err == ""


def test_combined_plan_prepares_both_stages(monkeypatch, tmp_path, capsys):
    site = ResolvedPlanItem(
        "site:new", "site", PlanAction.CREATE,
        ResolvedSiteValues("station", "Station"),
    )
    file = ResolvedPlanItem(
        "file:new", "file", PlanAction.CREATE,
        ResolvedFileValues(
            str(tmp_path / "unavailable.csv"),
            "UTC", "%Y", {"reader": "csv", "options": {}},
        ),
    )
    use_plan(monkeypatch, ResolvedPlan(metadata_items=(site,), raw_items=(file,)))
    path = write_config(tmp_path)

    assert main(["config", "plan", str(path)]) == 0
    captured = capsys.readouterr()
    assert "METADATA: CREATE=1" in captured.out
    assert "RAW: CREATE=1" in captured.out
    assert "Preparation checks passed" in captured.out
    assert captured.err == ""


def test_identity_change_is_inspected_but_still_requires_confirmation(
    monkeypatch,
    tmp_path,
    capsys,
):
    item = ResolvedPlanItem(
        "site:update",
        "site",
        PlanAction.UPDATE,
        ResolvedSiteValues("new", "Station"),
        database_id=7,
        changes=(FieldChange("site_code", "old", "new", True),),
    )
    resolved = ResolvedPlan(metadata_items=(item,))
    use_plan(monkeypatch, resolved)
    path = write_config(tmp_path)

    assert main(["config", "plan", str(path)]) == 0
    captured = capsys.readouterr()
    assert "Confirmation required: yes" in captured.out
    assert "[identity change]" in captured.out
    assert "Preparation checks passed" in captured.out
    assert "Confirmation is still required before applying" in captured.out
    assert resolved.requires_confirmation
    assert captured.err == ""


def test_dependency_cycle_fails_real_preparation(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(metadata, "find_site", lambda site_code: None)
    path = write_config(
        tmp_path,
        "sites:\n"
        "  - ref: a\n    site_code: a\n    name: A\n    parent: b\n"
        "  - ref: b\n    site_code: b\n    name: B\n    parent: a\n",
    )

    assert main(["config", "plan", str(path)]) == 2
    captured = capsys.readouterr()
    assert "CREATE=2" in captured.out
    assert "Preparation failed [PLAN_NOT_APPLICABLE]" in captured.err
    assert "Preparation checks passed" not in captured.out


def test_preparation_rejects_unsupported_resource(monkeypatch, tmp_path, capsys):
    item = ResolvedPlanItem(
        "unsupported",
        "unsupported",
        PlanAction.CREATE,
        ResolvedSiteValues("station", "Station"),
    )
    use_plan(monkeypatch, ResolvedPlan(metadata_items=(item,)))
    path = write_config(tmp_path)

    assert main(["config", "plan", str(path)]) == 2
    captured = capsys.readouterr()
    assert "Preparation failed [PLAN_NOT_APPLICABLE]" in captured.err
    assert "Preparation checks passed" not in captured.out


def test_plan_errors_skip_preparation(monkeypatch, tmp_path, capsys):
    resolved = ResolvedPlan(
        errors=(
            PlanError(
                PlanErrorCode.AMBIGUOUS,
                "sensor",
                "references.sensors.logger",
                "More than one sensor matches",
                (7, 9),
            ),
        ),
    )
    use_plan(monkeypatch, resolved)

    def unexpected_preparation(*args, **kwargs):
        pytest.fail("An invalid plan must not reach preparation")

    monkeypatch.setattr(configuration, "prepare_plan", unexpected_preparation)
    path = write_config(tmp_path)

    assert main(["config", "plan", str(path)]) == 2
    captured = capsys.readouterr()
    assert "AMBIGUOUS" in captured.out
    assert "candidate IDs: 7, 9" in captured.out
    assert "Planning blocked:" in captured.err


def test_warnings_do_not_block_planning(monkeypatch, tmp_path, capsys):
    resolved = replace(
        ResolvedPlan(),
        warnings=(PlanWarning("example", "sites[0]", "Review this site"),),
    )
    use_plan(monkeypatch, resolved)
    path = write_config(tmp_path)

    assert main(["config", "plan", str(path)]) == 0
    captured = capsys.readouterr()
    assert "Review this site" in captured.out
    assert "Preparation checks passed" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    "error",
    [
        psycopg.OperationalError("database unavailable"),
        RuntimeError("Missing required environment variable: POSTGRES_USER"),
    ],
)
def test_lookup_failures_are_operational_errors(
    error,
    monkeypatch,
    tmp_path,
    capsys,
):
    def fail_lookup(site_code):
        raise error

    monkeypatch.setattr(metadata, "find_site", fail_lookup)
    path = write_config(
        tmp_path,
        "sites:\n  - site_code: station\n    name: Station\n",
    )

    assert main(["config", "plan", str(path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"Configuration planning failed: {error}" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("argv", "expected_code"),
    [
        (["config", "plan", "--help"], 0),
        (["config", "plan"], 2),
        (["config", "plan", "config.yaml", "--yes"], 2),
    ],
)
def test_plan_argument_handling(argv, expected_code):
    with pytest.raises(SystemExit) as caught:
        main(argv)

    assert caught.value.code == expected_code


def test_module_entry_point_propagates_planning_failure(
    monkeypatch,
    tmp_path,
    capsys,
):
    def fail_lookup(site_code):
        raise psycopg.OperationalError("database unavailable")

    monkeypatch.setattr(metadata, "find_site", fail_lookup)
    path = write_config(
        tmp_path,
        "sites:\n  - site_code: station\n    name: Station\n",
    )
    monkeypatch.setattr(
        sys, "argv", ["dendroflow", "config", "plan", str(path)]
    )

    with pytest.raises(SystemExit) as caught:
        runpy.run_module("dendroflow", run_name="__main__")

    assert caught.value.code == 1
    assert "database unavailable" in capsys.readouterr().err

