from dendroflow.configuration import raw
from dendroflow.configuration.models import ConfigModel
from dendroflow.configuration.plan import (
    ExistingRef,
    PlanAction,
    PlanErrorCode,
    PlannedRef,
)
from dendroflow.configuration.raw import RawRow
from dendroflow.configuration.resolution.raw import (
    resolve_file_declarations,
)


def _file_config() -> ConfigModel:
    return ConfigModel(
        files=[
            {
                "ref": "sandhagen_water_table",
                "path": (
                    "tests/data/"
                    "Sandhagen_Rewetted_WaterTbl.dat"
                ),
                "timestamp": {
                    "timezone": "Etc/GMT-1",
                    "format": "%Y-%m-%d %H:%M:%S",
                },
                "reader": {
                    "type": "csv",
                    "options": {
                        "skiprows": [0, 2, 3],
                        "delimiter": ",",
                        "encoding": "utf-8",
                        "na_values": ["NAN"],
                    },
                },
                "interfaces": [
                    {
                        "deployment": "water_level_main",
                        "timestamp_column": "TIMESTAMP",
                        "values_column": "Lvl_cm_Avg",
                        "unit": "cm",
                    }
                ],
            }
        ]
    )


def test_new_file_becomes_create(monkeypatch):
    config = _file_config()

    monkeypatch.setattr(
        raw,
        "find_file",
        lambda filepath: None,
    )

    items, bindings, errors = resolve_file_declarations(
        config
    )

    assert errors == ()
    assert len(items) == 1
    assert len(bindings) == 1

    item = items[0]

    assert item.plan_id == "files[0]"
    assert item.resource_type == "file"
    assert item.action == PlanAction.CREATE
    assert item.database_id is None

    assert item.values.filepath == (
        "tests/data/Sandhagen_Rewetted_WaterTbl.dat"
    )
    assert item.values.timestamp_timezone == "Etc/GMT-1"
    assert item.values.timestamp_format == (
        "%Y-%m-%d %H:%M:%S"
    )
    assert item.values.reader_config == {
        "reader": "csv",
        "options": {
            "skiprows": [0, 2, 3],
            "delimiter": ",",
            "encoding": "utf-8",
            "na_values": ["NAN"],
        },
    }

    assert bindings[0].resource == PlannedRef(
        resource_type="file",
        plan_id="files[0]",
    )


def test_existing_matching_file_becomes_reuse(
    monkeypatch,
):
    config = _file_config()

    monkeypatch.setattr(
        raw,
        "find_file",
        lambda filepath: RawRow(
            database_id=3,
            values={
                "filepath": (
                    "tests/data/"
                    "Sandhagen_Rewetted_WaterTbl.dat"
                ),
                "timestamp_timezone": "Etc/GMT-1",
                "timestamp_format": (
                    "%Y-%m-%d %H:%M:%S"
                ),
                "reader_config": {
                    "reader": "csv",
                    "options": {
                        "skiprows": [0, 2, 3],
                        "delimiter": ",",
                        "encoding": "utf-8",
                        "na_values": ["NAN"],
                    },
                },
            },
        ),
    )

    items, bindings, errors = resolve_file_declarations(
        config
    )

    assert errors == ()
    assert len(items) == 1

    assert items[0].action == PlanAction.REUSE
    assert items[0].database_id == 3

    assert bindings[0].resource == ExistingRef(
        resource_type="file",
        database_id=3,
    )


def test_existing_file_timestamp_timezone_difference_conflicts(
    monkeypatch,
):
    config = _file_config()

    monkeypatch.setattr(
        raw,
        "find_file",
        lambda filepath: RawRow(
            database_id=3,
            values={
                "filepath": config.files[0].path,
                "timestamp_timezone": "UTC",
                "timestamp_format": (
                    "%Y-%m-%d %H:%M:%S"
                ),
                "reader_config": {
                    "reader": "csv",
                    "options": {
                        "skiprows": [0, 2, 3],
                        "delimiter": ",",
                        "encoding": "utf-8",
                        "na_values": ["NAN"],
                    },
                },
            },
        ),
    )

    items, bindings, errors = resolve_file_declarations(
        config
    )

    assert len(items) == 1
    assert items[0].action == PlanAction.REUSE
    assert items[0].database_id == 3

    assert len(bindings) == 1
    assert bindings[0].resource == ExistingRef(
        resource_type="file",
        database_id=3,
    )

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT
    assert errors[0].resource_type == "file"
    assert errors[0].source_path == "files[0].timestamp_timezone"


def test_existing_file_timestamp_format_difference_conflicts(
    monkeypatch,
):
    config = _file_config()

    monkeypatch.setattr(
        raw,
        "find_file",
        lambda filepath: RawRow(
            database_id=3,
            values={
                "filepath": config.files[0].path,
                "timestamp_timezone": "Etc/GMT-1",
                "timestamp_format": "%d.%m.%Y %H:%M",
                "reader_config": {
                    "reader": "csv",
                    "options": {
                        "skiprows": [0, 2, 3],
                        "delimiter": ",",
                        "encoding": "utf-8",
                        "na_values": ["NAN"],
                    },
                },
            },
        ),
    )

    items, _, errors = resolve_file_declarations(config)

    assert len(items) == 1
    assert items[0].action == PlanAction.REUSE

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT


def test_existing_file_reader_config_difference_conflicts(
    monkeypatch,
):
    config = _file_config()

    monkeypatch.setattr(
        raw,
        "find_file",
        lambda filepath: RawRow(
            database_id=3,
            values={
                "filepath": config.files[0].path,
                "timestamp_timezone": "Etc/GMT-1",
                "timestamp_format": (
                    "%Y-%m-%d %H:%M:%S"
                ),
                "reader_config": {
                    "reader": "csv",
                    "options": {
                        "skiprows": [0],
                        "delimiter": ";",
                        "encoding": "utf-8",
                        "na_values": ["NAN"],
                    },
                },
            },
        ),
    )

    items, bindings, errors = resolve_file_declarations(
        config
    )

    assert len(items) == 1
    assert items[0].action == PlanAction.REUSE
    assert items[0].database_id == 3

    assert bindings[0].resource == ExistingRef(
        resource_type="file",
        database_id=3,
    )

    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.CONFLICT


def test_existing_file_reports_all_configuration_conflicts(
    monkeypatch,
):
    config = _file_config()

    monkeypatch.setattr(
        raw,
        "find_file",
        lambda filepath: RawRow(
            database_id=3,
            values={
                "filepath": config.files[0].path,
                "timestamp_timezone": "UTC",
                "timestamp_format": "%d.%m.%Y",
                "reader_config": {
                    "reader": "csv",
                    "options": {},
                },
            },
        ),
    )

    items, _, errors = resolve_file_declarations(config)

    assert items[0].action == PlanAction.REUSE

    assert len(errors) == 3
    assert all(
        error.code == PlanErrorCode.CONFLICT
        for error in errors
    )

    assert {
        error.source_path
        for error in errors
    } == {
        "files[0].timestamp_timezone",
        "files[0].timestamp_format",
        "files[0].reader_config",
    }

