import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from dendroflow.configuration.workbook.preparation import (
    WorkbookExportError,
    prepare_workbook_export,
)
from dendroflow.configuration.workbook.schema import RESOURCE_SHEETS
from dendroflow.configuration.workbook.source import SOURCE_COLUMNS

START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def make_frames(records=None):
    records = records or {}
    return {
        name: pd.DataFrame(records.get(name, []), columns=columns, dtype=object)
        for name, columns in SOURCE_COLUMNS.items()
    }


@pytest.fixture
def records():
    # Two selected-site candidates, their ancestor, and a child site that must
    # not be included implicitly. Both deployments share a sensor and RAW file.
    return {
        "sites": [
            (1, "region", "Region", None, None, None, None),
            (2, "north", "North", None, 0.0, 12.0, 1),
            (3, "south", "South", None, None, None, 1),
            (4, "child", "Child", None, None, None, 2),
        ],
        "location_types": [(10, "well", None), (11, "unused", None)],
        "sensor_types": [(20, "logger", None)],
        "variables": [(30, "level", False, None), (31, "unused", True, None)],
        "sensor_models": [(40, "Maker", "Model", 20)],
        "sensors": [(50, "000012", 40, None)],
        "locations": [
            (60, 2, 10, None, None, None, 0.0),
            (61, 3, 10, None, None, None, None),
        ],
        "location_labels": [
            (70, 60, "North old", START, START + timedelta(days=10)),
            (71, 60, "North new", START + timedelta(days=10), None),
            (72, 61, "South well", START, None),
        ],
        "deployments": [
            (80, 50, 60, 30, START, START + timedelta(days=20)),
            (81, 50, 61, 30, START + timedelta(days=20), None),
        ],
        "files": [
            (90, "/data/shared.csv", "UTC", "%Y-%m-%d", {
                "reader": "csv", "options": {"skiprows": [0, 2], "na_values": ["NAN"]},
            }),
            (91, "/data/unreferenced.csv", "UTC", "%Y-%m-%d", {
                "reader": "csv", "options": {},
            }),
        ],
        "interfaces": [
            (100, 90, 80, "time", "north", "cm"),
            (101, 90, 81, "time", "south", "cm"),
        ],
    }


def change(frames, sheet, key, column, value):
    frame = frames[sheet]
    index = frame.index[frame.iloc[:, 0] == key][0]
    frame.at[index, column] = value


def row(export, sheet, key):
    frame = export.frames[sheet]
    return frame.loc[frame.iloc[:, 0] == str(key)].iloc[0]


def test_empty_all_export_preserves_every_sheet_and_header():
    export = prepare_workbook_export(make_frames())
    assert export.scope == "all"
    assert export.site_ids == ()
    for spec in RESOURCE_SHEETS:
        assert export.frames[spec.name].empty
        assert tuple(export.frames[spec.name].columns) == spec.headers


def test_all_export_includes_unreferenced_records_as_editable(records):
    export = prepare_workbook_export(make_frames(records))
    for spec in RESOURCE_SHEETS:
        frame = export.frames[spec.name]
        assert len(frame) == len(records[spec.name])
        assert tuple(frame.columns) == spec.headers
        assert set(frame["row_role"]) == {"edit"}
    assert row(export, "files", 91)["path"] == "/data/unreferenced.csv"
    assert row(export, "sites", 4)["ref"] == "site_4"


def test_site_scope_includes_exact_related_records_and_roles(records):
    export = prepare_workbook_export(make_frames(records), site_ids=[2])
    expected = {
        "sites": ["1", "2"], "location_types": ["10"], "sensor_types": ["20"],
        "variables": ["30"], "sensor_models": ["40"], "sensors": ["50"],
        "locations": ["60"], "location_labels": ["70", "71"],
        "deployments": ["80"], "files": ["90"], "interfaces": ["100"],
    }
    assert export.scope == "sites"
    assert export.site_ids == (2,)
    for name, ids in expected.items():
        assert export.frames[name].iloc[:, 0].tolist() == ids
    assert row(export, "sites", 1)["row_role"] == "reference"
    assert row(export, "sites", 2)["row_role"] == "edit"
    for name in ("locations", "location_labels", "deployments", "interfaces"):
        assert set(export.frames[name]["row_role"]) == {"edit"}
    for name in ("location_types", "sensor_types", "variables", "sensor_models", "sensors", "files"):
        assert set(export.frames[name]["row_role"]) == {"reference"}


def test_multiple_sites_deduplicate_shared_records_and_keep_selected_ancestor_editable(records):
    export = prepare_workbook_export(make_frames(records), site_ids=[3, 2, 1, 2])
    assert export.site_ids == (1, 2, 3)
    assert len(export.frames["files"]) == 1
    assert len(export.frames["sensors"]) == 1
    assert len(export.frames["interfaces"]) == 2
    assert set(export.frames["sites"]["row_role"]) == {"edit"}
    assert "4" not in export.frames["sites"]["site_id"].tolist()


def test_site_without_locations_exports_its_ancestor_chain(records):
    export = prepare_workbook_export(make_frames(records), site_ids=[4])
    assert export.frames["sites"]["site_id"].tolist() == ["1", "2", "4"]
    assert export.frames["locations"].empty
    assert row(export, "sites", 2)["row_role"] == "reference"


def test_all_relationship_cells_resolve_to_exported_aliases(records):
    export = prepare_workbook_export(make_frames(records), site_ids=[2])
    for spec in RESOURCE_SHEETS:
        for column in spec.fields:
            if column.target_sheet:
                targets = set(export.frames[column.target_sheet]["ref"])
                for reference in export.frames[spec.name][column.name]:
                    assert reference is None or reference in targets
    assert row(export, "interfaces", 100)["deployment"] == "deployment_80"
    assert row(export, "sensors", 50)["sensor_model"] == "sensor_model_40"


def test_input_row_column_and_mapping_order_do_not_change_output(records):
    frames = make_frames(records)
    baseline = prepare_workbook_export(frames)
    shuffled = {
        name: frame.iloc[::-1, ::-1].reset_index(drop=True)
        for name, frame in reversed(tuple(frames.items()))
    }
    actual = prepare_workbook_export(shuffled)
    assert tuple(actual.frames) == tuple(baseline.frames)
    for name in actual.frames:
        assert_frame_equal(actual.frames[name], baseline.frames[name])


def test_preparation_does_not_mutate_or_share_mutable_input(records):
    frames = make_frames(records)
    before = deepcopy(frames)
    export = prepare_workbook_export(frames)
    for name in frames:
        assert_frame_equal(frames[name], before[name])
    export.frames["sites"].at[0, "name"] = "Changed by caller"
    assert frames["sites"].at[0, "name"] == "Region"
    frames["files"].at[0, "reader_config"]["options"]["skiprows"].append(5)
    assert json.loads(row(export, "files", 90)["reader_options"])["skiprows"] == [0, 2]


def test_large_ids_and_leading_zeros_are_preserved():
    key = 2**63 - 1
    export = prepare_workbook_export(make_frames({
        "sites": [(key, "000001", "NA", None, 0.0, 0.0, None)],
    }))
    result = row(export, "sites", key)
    assert result["site_id"] == str(key)
    assert result["ref"] == f"site_{key}"
    assert result["site_code"] == "000001"
    assert result["name"] == "NA"
    assert result["description"] is None
    assert result["latitude"] == 0.0


def test_timestamps_normalize_to_utc_and_preserve_microseconds(records):
    frames = make_frames(records)
    when = datetime(2025, 1, 1, 2, 0, 0, 123456, tzinfo=timezone(timedelta(hours=2)))
    change(frames, "deployments", 80, "valid_from", when)
    export = prepare_workbook_export(frames)
    assert row(export, "deployments", 80)["valid_from"] == "2025-01-01T00:00:00.123456Z"
    assert row(export, "deployments", 81)["valid_to"] is None
    assert row(export, "variables", 30)["derived"] is False


def test_initial_label_uses_earliest_instant_then_id(records):
    frames = make_frames(records)
    # Input ID order and local clock time must not determine the initial label.
    earlier = START - timedelta(days=1)
    change(frames, "location_labels", 71, "valid_from", earlier)
    export = prepare_workbook_export(frames)
    assert row(export, "location_labels", 71)["is_initial"] is True
    assert row(export, "location_labels", 70)["is_initial"] is False
    change(frames, "location_labels", 70, "valid_from", earlier)
    export = prepare_workbook_export(frames)
    assert row(export, "location_labels", 70)["is_initial"] is True
    assert row(export, "location_labels", 71)["is_initial"] is False


def test_reader_settings_are_split_without_semantic_change(records):
    export = prepare_workbook_export(make_frames(records))
    result = row(export, "files", 90)
    assert result["path"] == "/data/shared.csv"
    assert result["reader_type"] == "csv"
    assert json.loads(result["reader_options"]) == records["files"][0][-1]["options"]


@pytest.mark.parametrize("site_ids", [[], [0], [-1], [True], [2.0], ["2"], [2**63], 2, "2"])
def test_invalid_site_selection_is_rejected(site_ids, records):
    with pytest.raises(ValueError, match="site_ids"):
        prepare_workbook_export(make_frames(records), site_ids=site_ids)


def test_unknown_site_is_reported(records):
    with pytest.raises(WorkbookExportError, match="selected site") as caught:
        prepare_workbook_export(make_frames(records), site_ids=[999])
    assert caught.value.database_id == 999


@pytest.mark.parametrize("defect", ["missing_sheet", "extra_sheet", "missing_column", "duplicate_column"])
def test_invalid_source_structure_is_rejected(defect, records):
    frames = make_frames(records)
    if defect == "missing_sheet":
        del frames["sites"]
    elif defect == "extra_sheet":
        frames["unexpected"] = pd.DataFrame()
    elif defect == "missing_column":
        frames["sites"] = frames["sites"].drop(columns="name")
    else:
        frames["sites"] = pd.concat([frames["sites"], frames["sites"][["name"]]], axis=1)
    with pytest.raises(WorkbookExportError):
        prepare_workbook_export(frames)


@pytest.mark.parametrize("key", [None, True, 1.5, "1", 0, 2**63])
def test_invalid_source_primary_id_is_rejected(key, records):
    frames = make_frames(records)
    frames["sites"].at[0, "site_id"] = key
    with pytest.raises(WorkbookExportError, match="BIGINT"):
        prepare_workbook_export(frames)


def test_duplicate_primary_id_is_rejected(records):
    frames = make_frames(records)
    frames["sites"].at[1, "site_id"] = 1
    with pytest.raises(WorkbookExportError, match="duplicate ID"):
        prepare_workbook_export(frames)


@pytest.mark.parametrize(("sheet", "key", "field", "missing"), [
    ("sites", 2, "parent_id", 999),
    ("sensors", 50, "sensor_model_id", 999),
    ("locations", 60, "location_type_id", None),
    ("interfaces", 100, "file_id", 999),
    ("interfaces", 100, "deployment_id", 999),
])
def test_missing_references_are_reported_with_source_location(records, sheet, key, field, missing):
    frames = make_frames(records)
    change(frames, sheet, key, field, missing)
    with pytest.raises(WorkbookExportError, match="referenced ID") as caught:
        prepare_workbook_export(frames)
    assert (caught.value.sheet, caught.value.database_id, caught.value.column) == (sheet, key, field)


@pytest.mark.parametrize("parent", [1, 2])
def test_ancestor_cycles_are_rejected_without_looping(records, parent):
    frames = make_frames(records)
    change(frames, "sites", 1, "parent_id", parent)
    with pytest.raises(WorkbookExportError, match="ancestor cycle"):
        prepare_workbook_export(frames, site_ids=[2])


def test_location_without_history_is_reported(records):
    frames = make_frames(records)
    frames["location_labels"] = frames["location_labels"].iloc[2:].copy()
    with pytest.raises(WorkbookExportError, match="no label history"):
        prepare_workbook_export(frames, site_ids=[2])


@pytest.mark.parametrize(("sheet", "key", "column", "value"), [
    ("sites", 2, "name", None),
    ("sites", 2, "name", " padded "),
    ("sites", 2, "description", ""),
    ("sites", 2, "name", "bad\x00text"),
    ("sites", 2, "name", "x" * 32768),
    ("sites", 2, "latitude", float("nan")),
    ("sites", 2, "latitude", float("inf")),
    ("sites", 2, "latitude", True),
    ("variables", 30, "derived", 0),
    ("deployments", 80, "valid_from", START.replace(tzinfo=None)),
    ("deployments", 80, "valid_from", "2025-01-01"),
    ("sensor_models", 40, "manufacturer", None),
    ("interfaces", 100, "unit", None),
])
def test_unrepresentable_cells_raise_located_errors(records, sheet, key, column, value):
    frames = make_frames(records)
    change(frames, sheet, key, column, value)
    with pytest.raises(WorkbookExportError) as caught:
        prepare_workbook_export(frames)
    assert (caught.value.sheet, caught.value.database_id, caught.value.column) == (sheet, key, column)


@pytest.mark.parametrize("reader", [
    {}, {"reader": "csv"}, {"reader": "csv", "options": {}, "extra": 1},
    {"reader": "other", "options": {}}, {"reader": "csv", "options": []},
    {"reader": "csv", "options": {"value": float("nan")}},
    {"reader": "csv", "options": {"value": START}},
    {"reader": "csv", "options": {"value": (1, 2)}},
])
def test_reader_config_is_not_silently_defaulted_or_truncated(records, reader):
    frames = make_frames(records)
    change(frames, "files", 90, "reader_config", reader)
    with pytest.raises(WorkbookExportError) as caught:
        prepare_workbook_export(frames)
    assert caught.value.sheet == "files"
    assert caught.value.database_id == 90


def test_invalid_values_outside_site_scope_do_not_block_export(records):
    frames = make_frames(records)
    change(frames, "files", 91, "reader_config", {})
    change(frames, "sites", 4, "name", " padded ")
    assert prepare_workbook_export(frames, site_ids=[2]).site_ids == (2,)
    with pytest.raises(WorkbookExportError):
        prepare_workbook_export(frames)


def test_invalid_required_reference_row_blocks_site_export(records):
    frames = make_frames(records)
    change(frames, "sensor_models", 40, "manufacturer", None)
    with pytest.raises(WorkbookExportError) as caught:
        prepare_workbook_export(frames, site_ids=[2])
    assert caught.value.sheet == "sensor_models"
    assert caught.value.column == "manufacturer"


def test_formula_like_strings_remain_literal_values_for_writer(records):
    frames = make_frames(records)
    change(frames, "sites", 2, "name", "=1+1")
    export = prepare_workbook_export(frames)
    assert row(export, "sites", 2)["name"] == "=1+1"


def test_preparation_performs_no_database_reads(records, monkeypatch):
    def fail_connect(*args, **kwargs):
        pytest.fail("preparation attempted a database connection")

    monkeypatch.setattr("dendroflow.configuration.workbook.source.connect", fail_connect)
    prepare_workbook_export(make_frames(records), site_ids=[2])
