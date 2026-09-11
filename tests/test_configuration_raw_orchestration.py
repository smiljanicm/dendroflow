from dendroflow.configuration import raw
from dendroflow.configuration.models import ConfigModel
from dendroflow.configuration.plan import (
    ExistingRef,
    PlanAction,
    PlanBinding,
    PlanErrorCode,
    PlannedRef,
)
from dendroflow.configuration.raw import RawRow
from dendroflow.configuration.resolution.orchestration import (
    resolve_raw_config,
)


def _raw_config() -> ConfigModel:
    return ConfigModel(
        references={
            "deployments": {
                "water_level_main": {
                    "valid_from": "2025-04-01T00:00:00Z",
                }
            }
        },
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
        ],
    )


def test_resolve_raw_config_empty_config():
    plan = resolve_raw_config(ConfigModel())

    assert plan.metadata_items == ()
    assert plan.raw_items == ()
    assert plan.bindings == ()
    assert plan.errors == ()
    assert plan.warnings == ()


def test_resolve_raw_config_builds_planned_raw_chain(
    monkeypatch,
):
    config = _raw_config()

    monkeypatch.setattr(
        raw,
        "find_file",
        lambda filepath: None,
    )

    deployment_binding = PlanBinding(
        resource_type="deployments",
        alias="water_level_main",
        resource=PlannedRef(
            resource_type="deployment",
            plan_id="deployments[0]",
        ),
    )

    plan = resolve_raw_config(
        config,
        existing_bindings=(deployment_binding,),
    )

    assert plan.metadata_items == ()
    assert plan.errors == ()
    assert plan.warnings == ()

    assert len(plan.raw_items) == 2

    file_item, interface_item = plan.raw_items

    assert file_item.plan_id == "files[0]"
    assert file_item.action == PlanAction.CREATE

    assert interface_item.plan_id == (
        "files[0].interfaces[0]"
    )
    assert interface_item.action == PlanAction.CREATE

    assert interface_item.values.file == PlannedRef(
        resource_type="file",
        plan_id="files[0]",
    )
    assert interface_item.values.deployment == PlannedRef(
        resource_type="deployment",
        plan_id="deployments[0]",
    )

    assert len(plan.bindings) == 1
    assert plan.bindings[0].alias == (
        "sandhagen_water_table"
    )


def test_resolve_raw_config_reuses_existing_raw_chain(
    monkeypatch,
):
    config = _raw_config()

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
                        "skiprows": [0, 2, 3],
                        "delimiter": ",",
                        "encoding": "utf-8",
                        "na_values": ["NAN"],
                    },
                },
            },
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
                    "deployment_id": 11,
                    "values_column": "Lvl_cm_Avg",
                    "timestamp_column": "TIMESTAMP",
                    "unit": "cm",
                },
            ),
        ),
    )

    deployment_binding = PlanBinding(
        resource_type="deployments",
        alias="water_level_main",
        resource=ExistingRef(
            resource_type="deployment",
            database_id=11,
        ),
    )

    plan = resolve_raw_config(
        config,
        existing_bindings=(deployment_binding,),
    )

    assert plan.errors == ()
    assert len(plan.raw_items) == 2

    file_item, interface_item = plan.raw_items

    assert file_item.action == PlanAction.REUSE
    assert file_item.database_id == 3

    assert interface_item.action == PlanAction.REUSE
    assert interface_item.database_id == 7

    assert plan.bindings[0].resource == ExistingRef(
        resource_type="file",
        database_id=3,
    )


def test_resolve_raw_config_accumulates_file_and_interface_errors(
    monkeypatch,
):
    config = _raw_config()

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

    monkeypatch.setattr(
        raw,
        "find_file_interfaces",
        lambda file_id: (),
    )

    plan = resolve_raw_config(
        config,
        existing_bindings=(),
    )

    assert len(plan.raw_items) == 1

    file_item = plan.raw_items[0]

    assert file_item.action == PlanAction.REUSE
    assert file_item.database_id == 3

    assert len(plan.errors) == 2

    assert {
        error.code
        for error in plan.errors
    } == {
        PlanErrorCode.CONFLICT,
        PlanErrorCode.INVALID_REFERENCE,
    }

    assert {
        error.source_path
        for error in plan.errors
    } == {
        "files[0].timestamp_timezone",
        "files[0].interfaces[0].deployment",
    }


# Orchestration hardening


def _interface(
    *,
    deployment="water_level_main",
    values_column="Lvl_cm_Avg",
    timestamp_column="TIMESTAMP",
    unit="cm",
):
    return {
        "deployment": deployment,
        "timestamp_column": timestamp_column,
        "values_column": values_column,
        "unit": unit,
    }


def _file(
    *,
    path,
    ref=None,
    interfaces=None,
):
    declaration = {
        "path": path,
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
        "interfaces": interfaces or [
            _interface()
        ],
    }

    if ref is not None:
        declaration["ref"] = ref

    return declaration


def _hardening_config(
    *,
    files,
    deployment_aliases=("water_level_main",),
):
    references = {
        alias: {
            "valid_from": (
                f"2025-04-{index + 1:02d}T00:00:00Z"
            )
        }
        for index, alias in enumerate(deployment_aliases)
    }

    return ConfigModel(
        references={
            "deployments": references,
        },
        files=files,
    )


def _existing_file_row(database_id, filepath):
    return RawRow(
        database_id=database_id,
        values={
            "filepath": filepath,
            "timestamp_timezone": "Etc/GMT-1",
            "timestamp_format": "%Y-%m-%d %H:%M:%S",
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
    )


def _deployment_binding(
    alias="water_level_main",
    database_id=11,
):
    return PlanBinding(
        resource_type="deployments",
        alias=alias,
        resource=ExistingRef(
            resource_type="deployment",
            database_id=database_id,
        ),
    )


def test_multiple_files_mix_create_and_reuse(
    monkeypatch,
):
    existing_path = "tests/data/existing.dat"
    new_path = "tests/data/new.dat"

    config = _hardening_config(
        files=[
            _file(
                path=existing_path,
                ref="existing_file",
            ),
            _file(
                path=new_path,
                ref="new_file",
            ),
        ]
    )

    def fake_find_file(filepath):
        if filepath == existing_path:
            return _existing_file_row(3, filepath)
        if filepath == new_path:
            return None
        raise AssertionError(f"unexpected filepath: {filepath}")

    monkeypatch.setattr(
        raw,
        "find_file",
        fake_find_file,
    )

    monkeypatch.setattr(
        raw,
        "find_file_interfaces",
        lambda file_id: (
            RawRow(
                database_id=7,
                values={
                    "file_id": 3,
                    "deployment_id": 11,
                    "values_column": "Lvl_cm_Avg",
                    "timestamp_column": "TIMESTAMP",
                    "unit": "cm",
                },
            ),
        ),
    )

    plan = resolve_raw_config(
        config,
        existing_bindings=(
            _deployment_binding(),
        ),
    )

    assert plan.errors == ()
    assert len(plan.raw_items) == 4

    assert [
        item.action
        for item in plan.raw_items
    ] == [
        PlanAction.REUSE,
        PlanAction.CREATE,
        PlanAction.REUSE,
        PlanAction.CREATE,
    ]


def test_existing_file_resolves_multiple_interfaces(
    monkeypatch,
):
    filepath = "tests/data/existing.dat"

    config = _hardening_config(
        files=[
            _file(
                path=filepath,
                interfaces=[
                    _interface(
                        values_column="Lvl_cm_Avg",
                        unit="cm",
                    ),
                    _interface(
                        values_column="Temp_C_Avg",
                        unit="deg C",
                    ),
                ],
            )
        ]
    )

    monkeypatch.setattr(
        raw,
        "find_file",
        lambda path: _existing_file_row(3, path),
    )

    monkeypatch.setattr(
        raw,
        "find_file_interfaces",
        lambda file_id: (
            RawRow(
                database_id=7,
                values={
                    "file_id": 3,
                    "deployment_id": 11,
                    "values_column": "Lvl_cm_Avg",
                    "timestamp_column": "TIMESTAMP",
                    "unit": "cm",
                },
            ),
            RawRow(
                database_id=8,
                values={
                    "file_id": 3,
                    "deployment_id": 11,
                    "values_column": "Temp_C_Avg",
                    "timestamp_column": "TIMESTAMP",
                    "unit": "deg C",
                },
            ),
        ),
    )

    plan = resolve_raw_config(
        config,
        existing_bindings=(
            _deployment_binding(),
        ),
    )

    assert plan.errors == ()
    assert len(plan.raw_items) == 3

    assert [
        item.action
        for item in plan.raw_items
    ] == [
        PlanAction.REUSE,
        PlanAction.REUSE,
        PlanAction.REUSE,
    ]

    assert plan.raw_items[1].database_id == 7
    assert plan.raw_items[2].database_id == 8


def test_existing_file_mixes_reused_and_new_interfaces(
    monkeypatch,
):
    filepath = "tests/data/existing.dat"

    config = _hardening_config(
        files=[
            _file(
                path=filepath,
                interfaces=[
                    _interface(
                        values_column="Lvl_cm_Avg",
                        unit="cm",
                    ),
                    _interface(
                        values_column="Temp_C_Avg",
                        unit="deg C",
                    ),
                ],
            )
        ]
    )

    monkeypatch.setattr(
        raw,
        "find_file",
        lambda path: _existing_file_row(3, path),
    )

    monkeypatch.setattr(
        raw,
        "find_file_interfaces",
        lambda file_id: (
            RawRow(
                database_id=7,
                values={
                    "file_id": 3,
                    "deployment_id": 11,
                    "values_column": "Lvl_cm_Avg",
                    "timestamp_column": "TIMESTAMP",
                    "unit": "cm",
                },
            ),
        ),
    )

    plan = resolve_raw_config(
        config,
        existing_bindings=(
            _deployment_binding(),
        ),
    )

    assert plan.errors == ()
    assert len(plan.raw_items) == 3

    file_item, first_interface, second_interface = (
        plan.raw_items
    )

    assert file_item.action == PlanAction.REUSE

    assert first_interface.action == PlanAction.REUSE
    assert first_interface.database_id == 7

    assert second_interface.action == PlanAction.CREATE
    assert second_interface.database_id is None

    assert second_interface.values.values_column == (
        "Temp_C_Avg"
    )


def test_planned_file_with_multiple_interfaces_skips_raw_lookup(
    monkeypatch,
):
    filepath = "tests/data/new.dat"

    config = _hardening_config(
        files=[
            _file(
                path=filepath,
                interfaces=[
                    _interface(
                        values_column="Lvl_cm_Avg",
                        unit="cm",
                    ),
                    _interface(
                        values_column="Temp_C_Avg",
                        unit="deg C",
                    ),
                ],
            )
        ]
    )

    monkeypatch.setattr(
        raw,
        "find_file",
        lambda path: None,
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

    plan = resolve_raw_config(
        config,
        existing_bindings=(
            _deployment_binding(),
        ),
    )

    assert plan.errors == ()

    assert [
        item.action
        for item in plan.raw_items
    ] == [
        PlanAction.CREATE,
        PlanAction.CREATE,
        PlanAction.CREATE,
    ]


def test_unresolved_deployment_does_not_block_valid_interface(
    monkeypatch,
):
    filepath = "tests/data/new.dat"

    config = _hardening_config(
        deployment_aliases=(
            "water_level_main",
            "unresolved_deployment",
        ),
        files=[
            _file(
                path=filepath,
                interfaces=[
                    _interface(
                        deployment="water_level_main",
                        values_column="Lvl_cm_Avg",
                    ),
                    _interface(
                        deployment="unresolved_deployment",
                        values_column="Temp_C_Avg",
                        unit="deg C",
                    ),
                ],
            )
        ],
    )

    monkeypatch.setattr(
        raw,
        "find_file",
        lambda path: None,
    )

    plan = resolve_raw_config(
        config,
        existing_bindings=(
            _deployment_binding(
                alias="water_level_main",
                database_id=11,
            ),
        ),
    )

    assert len(plan.raw_items) == 2

    file_item, valid_interface = plan.raw_items

    assert file_item.action == PlanAction.CREATE
    assert valid_interface.action == PlanAction.CREATE
    assert valid_interface.values.values_column == (
        "Lvl_cm_Avg"
    )

    assert len(plan.errors) == 1
    assert (
        plan.errors[0].code
        == PlanErrorCode.INVALID_REFERENCE
    )
    assert plan.errors[0].source_path == (
        "files[0].interfaces[1].deployment"
    )


def test_conflicting_interface_does_not_block_later_interface(
    monkeypatch,
):
    filepath = "tests/data/existing.dat"

    config = _hardening_config(
        files=[
            _file(
                path=filepath,
                interfaces=[
                    _interface(
                        values_column="Lvl_cm_Avg",
                        unit="cm",
                    ),
                    _interface(
                        values_column="Temp_C_Avg",
                        unit="deg C",
                    ),
                ],
            )
        ]
    )

    monkeypatch.setattr(
        raw,
        "find_file",
        lambda path: _existing_file_row(3, path),
    )

    monkeypatch.setattr(
        raw,
        "find_file_interfaces",
        lambda file_id: (
            RawRow(
                database_id=7,
                values={
                    "file_id": 3,
                    "deployment_id": 11,
                    "values_column": "Lvl_cm_Avg",
                    "timestamp_column": "TIMESTAMP",
                    "unit": "m",
                },
            ),
        ),
    )

    plan = resolve_raw_config(
        config,
        existing_bindings=(
            _deployment_binding(),
        ),
    )

    assert len(plan.raw_items) == 3

    file_item, conflicting_interface, new_interface = (
        plan.raw_items
    )

    assert file_item.action == PlanAction.REUSE

    assert conflicting_interface.action == PlanAction.REUSE
    assert conflicting_interface.database_id == 7

    assert new_interface.action == PlanAction.CREATE
    assert new_interface.values.values_column == (
        "Temp_C_Avg"
    )

    assert len(plan.errors) == 1
    assert plan.errors[0].code == PlanErrorCode.CONFLICT
    assert plan.errors[0].source_path == (
        "files[0].interfaces[0].unit"
    )


def test_raw_items_have_deterministic_order(
    monkeypatch,
):
    first_path = "tests/data/first.dat"
    second_path = "tests/data/second.dat"

    config = _hardening_config(
        files=[
            _file(
                path=first_path,
                interfaces=[
                    _interface(
                        values_column="First_A",
                    ),
                    _interface(
                        values_column="First_B",
                    ),
                ],
            ),
            _file(
                path=second_path,
                interfaces=[
                    _interface(
                        values_column="Second_A",
                    ),
                ],
            ),
        ]
    )

    monkeypatch.setattr(
        raw,
        "find_file",
        lambda path: None,
    )

    plan = resolve_raw_config(
        config,
        existing_bindings=(
            _deployment_binding(),
        ),
    )

    assert plan.errors == ()

    assert [
        item.plan_id
        for item in plan.raw_items
    ] == [
        "files[0]",
        "files[1]",
        "files[0].interfaces[0]",
        "files[0].interfaces[1]",
        "files[1].interfaces[0]",
    ]


def test_file_without_ref_creates_no_binding(
    monkeypatch,
):
    filepath = "tests/data/no_ref.dat"

    config = _hardening_config(
        files=[
            _file(
                path=filepath,
                ref=None,
            )
        ]
    )

    monkeypatch.setattr(
        raw,
        "find_file",
        lambda path: None,
    )

    plan = resolve_raw_config(
        config,
        existing_bindings=(
            _deployment_binding(),
        ),
    )

    assert plan.errors == ()
    assert len(plan.raw_items) == 2

    assert plan.raw_items[0].action == PlanAction.CREATE
    assert plan.raw_items[1].action == PlanAction.CREATE

    assert plan.bindings == ()

