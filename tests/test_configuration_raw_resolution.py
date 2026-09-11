from dendroflow.configuration import raw
from dendroflow.configuration.models import ConfigModel
from dendroflow.configuration.plan import (
    ExistingRef,
    PlanAction,
    PlanBinding,
    PlanErrorCode,
    PlannedRef,
    ResolvedFileValues,
    ResolvedPlanItem,
)
from dendroflow.configuration.raw import RawRow
from dendroflow.configuration.resolution.raw import (
    resolve_file_declarations,
    resolve_interface_declarations,
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


# Interface tests


def test_interface_for_new_file_becomes_create():
    config = _file_config()

    file_items = (
        ResolvedPlanItem(
            plan_id="files[0]",
            resource_type="file",
            action=PlanAction.CREATE,
            values=ResolvedFileValues(
                filepath=config.files[0].path,
                timestamp_timezone=(
                    config.files[0].timestamp.timezone
                ),
                timestamp_format=config.files[0].timestamp.format,
                reader_config={
                    "reader": "csv",
                    "options": config.files[0].reader.options,
                },
            ),
            source_path="files[0]",
        ),
    )

    deployment_ref = PlannedRef(
        resource_type="deployment",
        plan_id="deployments[0]",
    )

    existing_bindings = (
        PlanBinding(
            resource_type="deployments",
            alias="water_level_main",
            resource=deployment_ref,
        ),
    )

    items, errors = resolve_interface_declarations(
        config,
        file_items,
        existing_bindings,
    )

    assert errors == ()
    assert len(items) == 1

    assert items[0].plan_id == "files[0].interfaces[0]"
    assert items[0].action == PlanAction.CREATE

    assert items[0].values.file == PlannedRef(
        resource_type="file",
        plan_id="files[0]",
    )
    assert items[0].values.deployment == deployment_ref
    assert items[0].values.values_column == "Lvl_cm_Avg"


def test_new_file_interfaces_do_not_query_database(
    monkeypatch,
):
    config = _file_config()

    file_items = (
        ResolvedPlanItem(
            plan_id="files[0]",
            resource_type="file",
            action=PlanAction.CREATE,
            values=ResolvedFileValues(
                filepath=config.files[0].path,
                timestamp_timezone=(
                    config.files[0].timestamp.timezone
                ),
                timestamp_format=(
                    config.files[0].timestamp.format
                ),
                reader_config={
                    "reader": "csv",
                    "options": config.files[0].reader.options,
                },
            ),
            source_path="files[0]",
        ),
    )

    existing_bindings = (
        PlanBinding(
            resource_type="deployments",
            alias="water_level_main",
            resource=PlannedRef(
                resource_type="deployment",
                plan_id="deployments[0]",
            ),
        ),
    )

    def fail_if_called(file_id):
        raise AssertionError(
            "find_file_interfaces should not be called "
            "for a planned file"
        )

    monkeypatch.setattr(
        raw,
        "find_file_interfaces",
        fail_if_called,
    )

    items, errors = resolve_interface_declarations(
        config,
        file_items,
        existing_bindings,
    )

    assert errors == ()
    assert len(items) == 1
    assert items[0].action == PlanAction.CREATE


def test_new_interface_for_existing_file_becomes_create(
    monkeypatch,
):
    config = _file_config()

    file_items = (
        ResolvedPlanItem(
            plan_id="files[0]",
            resource_type="file",
            action=PlanAction.REUSE,
            database_id=3,
            values=ResolvedFileValues(
                filepath=config.files[0].path,
                timestamp_timezone=(
                    config.files[0].timestamp.timezone
                ),
                timestamp_format=(
                    config.files[0].timestamp.format
                ),
                reader_config={
                    "reader": "csv",
                    "options": config.files[0].reader.options,
                },
            ),
            source_path="files[0]",
        ),
    )

    existing_bindings = (
        PlanBinding(
            resource_type="deployments",
            alias="water_level_main",
            resource=ExistingRef(
                resource_type="deployment",
                database_id=11,
            ),
        ),
    )

    received_file_ids = []

    def fake_find_file_interfaces(file_id):
        received_file_ids.append(file_id)
        return ()

    monkeypatch.setattr(
        raw,
        "find_file_interfaces",
        fake_find_file_interfaces,
    )

    items, errors = resolve_interface_declarations(
        config,
        file_items,
        existing_bindings,
    )

    assert errors == ()
    assert received_file_ids == [3]
    assert len(items) == 1

    item = items[0]

    assert item.plan_id == "files[0].interfaces[0]"
    assert item.resource_type == "interface"
    assert item.action == PlanAction.CREATE
    assert item.database_id is None

    assert item.values.file == ExistingRef(
        resource_type="file",
        database_id=3,
    )
    assert item.values.deployment == ExistingRef(
        resource_type="deployment",
        database_id=11,
    )
    assert item.values.timestamp_column == "TIMESTAMP"
    assert item.values.values_column == "Lvl_cm_Avg"
    assert item.values.unit == "cm"


def test_existing_matching_interface_becomes_reuse(
    monkeypatch,
):
    config = _file_config()

    file_items = (
        ResolvedPlanItem(
            plan_id="files[0]",
            resource_type="file",
            action=PlanAction.REUSE,
            database_id=3,
            values=ResolvedFileValues(
                filepath=config.files[0].path,
                timestamp_timezone="Etc/GMT-1",
                timestamp_format="%Y-%m-%d %H:%M:%S",
                reader_config={
                    "reader": "csv",
                    "options": config.files[0].reader.options,
                },
            ),
            source_path="files[0]",
        ),
    )

    existing_bindings = (
        PlanBinding(
            resource_type="deployments",
            alias="water_level_main",
            resource=ExistingRef(
                resource_type="deployment",
                database_id=21,
            ),
        ),
    )

    monkeypatch.setattr(
        raw,
        "find_file_interfaces",
        lambda file_id: (
            RawRow(
                database_id=10,
                values={
                    "file_id": 3,
                    "deployment_id": 21,
                    "values_column": "Lvl_cm_Avg",
                    "timestamp_column": "TIMESTAMP",
                    "unit": "cm",
                },
            ),
        ),
    )

    items, errors = resolve_interface_declarations(
        config,
        file_items,
        existing_bindings,
    )

    assert errors == ()
    assert len(items) == 1
    assert items[0].action == PlanAction.REUSE
    assert items[0].database_id == 10


def test_existing_interface_configuration_difference_conflicts(
    monkeypatch,
):
    config = _file_config()

    file_items = (
        ResolvedPlanItem(
            plan_id="files[0]",
            resource_type="file",
            action=PlanAction.REUSE,
            database_id=3,
            values=ResolvedFileValues(
                filepath=config.files[0].path,
                timestamp_timezone=(
                    config.files[0].timestamp.timezone
                ),
                timestamp_format=(
                    config.files[0].timestamp.format
                ),
                reader_config={
                    "reader": "csv",
                    "options": config.files[0].reader.options,
                },
            ),
            source_path="files[0]",
        ),
    )

    existing_bindings = (
        PlanBinding(
            resource_type="deployments",
            alias="water_level_main",
            resource=ExistingRef(
                resource_type="deployment",
                database_id=11,
            ),
        ),
    )

    monkeypatch.setattr(
        raw,
        "find_file_interfaces",
        lambda file_id: (
            RawRow(
                database_id=7,
                values={
                    "file_id": 3,
                    "deployment_id": 99,
                    "values_column": "Lvl_cm_Avg",
                    "timestamp_column": "DATE_TIME",
                    "unit": "m",
                },
            ),
        ),
    )

    items, errors = resolve_interface_declarations(
        config,
        file_items,
        existing_bindings,
    )

    assert len(items) == 1

    item = items[0]

    assert item.action == PlanAction.REUSE
    assert item.database_id == 7

    assert len(errors) == 3
    assert all(
        error.code == PlanErrorCode.CONFLICT
        for error in errors
    )

    assert {
        error.source_path
        for error in errors
    } == {
        "files[0].interfaces[0].deployment",
        "files[0].interfaces[0].timestamp_column",
        "files[0].interfaces[0].unit",
    }


def test_interface_missing_deployment_binding_is_invalid():
    config = _file_config()

    file_items = (
        ResolvedPlanItem(
            plan_id="files[0]",
            resource_type="file",
            action=PlanAction.CREATE,
            values=ResolvedFileValues(
                filepath=config.files[0].path,
                timestamp_timezone=(
                    config.files[0].timestamp.timezone
                ),
                timestamp_format=(
                    config.files[0].timestamp.format
                ),
                reader_config={
                    "reader": "csv",
                    "options": config.files[0].reader.options,
                },
            ),
            source_path="files[0]",
        ),
    )

    items, errors = resolve_interface_declarations(
        config,
        file_items,
        existing_bindings=(),
    )

    assert items == ()
    assert len(errors) == 1

    error = errors[0]

    assert error.code == PlanErrorCode.INVALID_REFERENCE
    assert error.resource_type == "interface"
    assert error.source_path == (
        "files[0].interfaces[0].deployment"
    )

