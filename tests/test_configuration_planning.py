from dendroflow.configuration import metadata as metadata_db
from dendroflow.configuration import raw as raw_db
from dendroflow.configuration.metadata import MetadataRow
from dendroflow.configuration.parser import load_config
from dendroflow.configuration.plan import (
    ExistingRef,
    PlanAction,
    PlannedRef,
    ResolvedFileValues,
    ResolvedInterfaceValues,
)
from dendroflow.configuration.resolution.orchestration import (
    resolve_config,
)


def test_mixed_yaml_builds_applicable_plan(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sites:
  - ref: new_site
    site_code: TEST01
    name: Test Site

references:
  deployments:
    water_level_main:
      valid_from: "2025-01-01T00:00:00+00:00"

files:
  - ref: water_table_file
    path: tests/data/example.csv
    timestamp:
      timezone: Etc/GMT-1
      format: "%Y-%m-%d %H:%M:%S"
    reader:
      type: csv
      options:
        delimiter: ","
    interfaces:
      - deployment: water_level_main
        timestamp_column: TIMESTAMP
        values_column: Lvl_cm_Avg
        unit: cm
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        metadata_db,
        "find_site",
        lambda site_code: None,
    )

    def fake_find_deployments(
        *,
        sensor_id=None,
        location_id=None,
        variable_id=None,
        valid_from=None,
    ):
        assert sensor_id is None
        assert location_id is None
        assert variable_id is None

        if valid_from is None:
            return ()

        return (
            MetadataRow(
                database_id=41,
                values={
                    "sensor_id": 11,
                    "location_id": 21,
                    "variable_id": 31,
                    "valid_from": valid_from,
                    "valid_to": None,
                },
            ),
        )

    monkeypatch.setattr(
        metadata_db,
        "find_deployments",
        fake_find_deployments,
    )

    monkeypatch.setattr(
        raw_db,
        "find_file",
        lambda filepath: None,
    )

    config = load_config(config_path)
    plan = resolve_config(config)

    assert plan.errors == ()
    assert plan.can_apply is True
    assert plan.requires_confirmation is False

    assert tuple(
        item.plan_id
        for item in plan.metadata_items
    ) == (
        "sites[0]",
    )

    assert tuple(
        item.plan_id
        for item in plan.raw_items
    ) == (
        "files[0]",
        "files[0].interfaces[0]",
    )

    site_item = plan.metadata_items[0]

    assert site_item.resource_type == "site"
    assert site_item.action == PlanAction.CREATE
    assert site_item.database_id is None

    file_item = plan.raw_items[0]

    assert file_item.resource_type == "file"
    assert file_item.action == PlanAction.CREATE
    assert file_item.database_id is None
    assert isinstance(
        file_item.values,
        ResolvedFileValues,
    )
    assert file_item.values.filepath == (
        "tests/data/example.csv"
    )
    assert file_item.values.reader_config == {
        "reader": "csv",
        "options": {
            "delimiter": ",",
        },
    }

    interface_item = plan.raw_items[1]

    assert interface_item.resource_type == "interface"
    assert interface_item.action == PlanAction.CREATE
    assert isinstance(
        interface_item.values,
        ResolvedInterfaceValues,
    )

    assert interface_item.values.file == PlannedRef(
        resource_type="file",
        plan_id="files[0]",
    )
    assert interface_item.values.deployment == ExistingRef(
        resource_type="deployment",
        database_id=41,
    )

    assert tuple(
        binding.alias
        for binding in plan.bindings
    ) == (
        "new_site",
        "water_level_main",
        "water_table_file",
    )


