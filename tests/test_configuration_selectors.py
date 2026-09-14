from datetime import datetime, timezone

from dendroflow.configuration import metadata
from dendroflow.configuration.metadata import MetadataRow
from dendroflow.configuration.models import (
    DeploymentLookupConfig,
    LocationLookupConfig,
    SensorLookupConfig,
    SensorModelLookupConfig,
    SiteLookupConfig,
)
from dendroflow.configuration.plan import (
    ExistingRef,
    PlanBinding,
    PlanErrorCode,
    PlannedRef,
)
from dendroflow.configuration.resolution.selectors import (
    resolve_deployment_selector,
    resolve_location_selector,
    resolve_sensor_model_selector,
    resolve_sensor_selector,
    resolve_site_selector,
)


def test_sensor_selector_resolves_unique_match(
    monkeypatch,
):
    selector = SensorLookupConfig(
        serial_number="123456"
    )

    row = MetadataRow(
        database_id=7,
        values={
            "sensor_model_id": 3,
            "serial_number": "123456",
            "description": None,
        },
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (row,),
    )

    result, errors = resolve_sensor_selector(
        selector,
        source_path="updates.sensors[0].update",
    )

    assert errors == ()
    assert result == row


def test_sensor_selector_reports_not_found(
    monkeypatch,
):
    selector = SensorLookupConfig(
        serial_number="missing"
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (),
    )

    row, errors = resolve_sensor_selector(
        selector,
        source_path="updates.sensors[0].update",
    )

    assert row is None
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.NOT_FOUND
    assert errors[0].source_path == (
        "updates.sensors[0].update"
    )


def test_sensor_selector_reports_ambiguity(
    monkeypatch,
):
    selector = SensorLookupConfig(
        serial_number="123456"
    )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        lambda **kwargs: (
            MetadataRow(7, {}),
            MetadataRow(8, {}),
        ),
    )

    row, errors = resolve_sensor_selector(
        selector,
        source_path="updates.sensors[0].update",
    )

    assert row is None
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.AMBIGUOUS
    assert errors[0].candidate_ids == (7, 8)


def test_deployment_selector_resolves_unique_match(
    monkeypatch,
):
    valid_from = datetime(
        2025,
        4,
        1,
        tzinfo=timezone.utc,
    )

    selector = DeploymentLookupConfig(
        valid_from=valid_from
    )

    row = MetadataRow(
        database_id=21,
        values={
            "sensor_id": 7,
            "location_id": 5,
            "variable_id": 2,
            "valid_from": valid_from,
            "valid_to": None,
        },
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (row,),
    )

    result, errors = resolve_deployment_selector(
        selector,
        source_path="updates.deployments[0].update",
    )

    assert errors == ()
    assert result == row


def test_deployment_selector_reports_not_found(
    monkeypatch,
):
    selector = DeploymentLookupConfig(
        valid_from=datetime(
            2025,
            4,
            1,
            tzinfo=timezone.utc,
        )
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (),
    )

    row, errors = resolve_deployment_selector(
        selector,
        source_path="updates.deployments[0].update",
    )

    assert row is None
    assert errors[0].code == PlanErrorCode.NOT_FOUND


def test_deployment_selector_reports_ambiguity(
    monkeypatch,
):
    selector = DeploymentLookupConfig(
        valid_from=datetime(
            2025,
            4,
            1,
            tzinfo=timezone.utc,
        )
    )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        lambda **kwargs: (
            MetadataRow(21, {}),
            MetadataRow(22, {}),
        ),
    )

    row, errors = resolve_deployment_selector(
        selector,
        source_path="updates.deployments[0].update",
    )

    assert row is None
    assert errors[0].code == PlanErrorCode.AMBIGUOUS
    assert errors[0].candidate_ids == (21, 22)


def test_sensor_selector_missing_sensor_model_binding_is_invalid(
    monkeypatch,
):
    selector = SensorLookupConfig(
        serial_number="123456",
        sensor_model="cs451",
    )

    def fail_if_called(**kwargs):
        raise AssertionError(
            "find_sensors should not be called when "
            "sensor_model cannot be resolved"
        )

    monkeypatch.setattr(
        metadata,
        "find_sensors",
        fail_if_called,
    )

    row, errors = resolve_sensor_selector(
        selector,
        source_path="updates.sensors[0].update",
        existing_bindings=(),
    )

    assert row is None
    assert len(errors) == 1

    error = errors[0]

    assert error.code == PlanErrorCode.INVALID_REFERENCE
    assert error.resource_type == "sensor"
    assert error.source_path == (
        "updates.sensors[0].update.sensor_model"
    )


def test_deployment_selector_planned_relationship_is_invalid(
    monkeypatch,
):
    selector = DeploymentLookupConfig(
        sensor="sensor_01",
    )

    existing_bindings = (
        PlanBinding(
            resource_type="sensors",
            alias="sensor_01",
            resource=PlannedRef(
                resource_type="sensor",
                plan_id="sensors[0]",
            ),
        ),
    )

    def fail_if_called(**kwargs):
        raise AssertionError(
            "find_deployments should not be called when "
            "a selector relationship is only planned"
        )

    monkeypatch.setattr(
        metadata,
        "find_deployments",
        fail_if_called,
    )

    row, errors = resolve_deployment_selector(
        selector,
        source_path="updates.deployments[0].update",
        existing_bindings=existing_bindings,
    )

    assert row is None
    assert len(errors) == 1

    error = errors[0]

    assert error.code == PlanErrorCode.INVALID_REFERENCE
    assert error.resource_type == "deployment"
    assert error.source_path == (
        "updates.deployments[0].update.sensor"
    )


def test_site_selector_resolves_unique_match(
    monkeypatch,
):
    selector = SiteLookupConfig(
        site_code="SAN",
    )

    row = MetadataRow(
        database_id=11,
        values={
            "site_code": "SAN",
            "name": "Sandhagen",
            "description": None,
            "latitude": None,
            "longitude": None,
            "parent_id": None,
        },
    )

    monkeypatch.setattr(
        metadata,
        "find_site",
        lambda site_code: row,
    )

    result, errors = resolve_site_selector(
        selector,
        source_path="updates.sites[0].update",
    )

    assert errors == ()
    assert result == row


def test_site_selector_reports_not_found(
    monkeypatch,
):
    selector = SiteLookupConfig(
        site_code="missing",
    )

    monkeypatch.setattr(
        metadata,
        "find_site",
        lambda site_code: None,
    )

    row, errors = resolve_site_selector(
        selector,
        source_path="updates.sites[0].update",
    )

    assert row is None
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.NOT_FOUND
    assert errors[0].resource_type == "site"
    assert errors[0].source_path == (
        "updates.sites[0].update"
    )


def test_sensor_model_selector_reports_ambiguous(monkeypatch):
    selector = SensorModelLookupConfig(
        manufacturer="Campbell Scientific",
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: [
            MetadataRow(
                database_id=51,
                values={},
            ),
            MetadataRow(
                database_id=52,
                values={},
            ),
        ],
    )

    row, errors = resolve_sensor_model_selector(
        selector,
        source_path="updates.sensor_models[0].update",
    )

    assert row is None
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.AMBIGUOUS
    assert errors[0].resource_type == "sensor_model"


def test_sensor_model_selector_resolves_unique_match(
    monkeypatch,
):
    selector = SensorModelLookupConfig(
        manufacturer="Campbell Scientific",
        model="CS451",
    )

    row = MetadataRow(
        database_id=51,
        values={
            "model": "CS451",
            "manufacturer": "Campbell Scientific",
            "sensor_type_id": 31,
        },
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (row,),
    )

    result, errors = resolve_sensor_model_selector(
        selector,
        source_path="updates.sensor_models[0].update",
    )

    assert errors == ()
    assert result == row


def test_sensor_model_selector_reports_not_found(
    monkeypatch,
):
    selector = SensorModelLookupConfig(
        model="missing",
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (),
    )

    row, errors = resolve_sensor_model_selector(
        selector,
        source_path="updates.sensor_models[0].update",
    )

    assert row is None
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.NOT_FOUND
    assert errors[0].resource_type == "sensor_model"


def test_sensor_model_selector_reports_ambiguity(
    monkeypatch,
):
    selector = SensorModelLookupConfig(
        manufacturer="Campbell Scientific",
    )

    monkeypatch.setattr(
        metadata,
        "find_sensor_models",
        lambda **kwargs: (
            MetadataRow(51, {}),
            MetadataRow(52, {}),
        ),
    )

    row, errors = resolve_sensor_model_selector(
        selector,
        source_path="updates.sensor_models[0].update",
    )

    assert row is None
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.AMBIGUOUS
    assert errors[0].candidate_ids == (51, 52)


def test_location_selector_resolves_unique_match(
    monkeypatch,
):
    selector = LocationLookupConfig(
        site="sandhagen",
        initial_label="tree_001",
    )

    existing_bindings = (
        PlanBinding(
            resource_type="sites",
            alias="sandhagen",
            resource=ExistingRef(
                resource_type="site",
                database_id=11,
            ),
        ),
    )

    row = MetadataRow(
        database_id=71,
        values={
            "site_id": 11,
            "location_type_id": 21,
            "latitude": None,
            "longitude": None,
            "height_above_ground": None,
            "azimuth": None,
            "initial_label": "tree_001",
            "initial_label_valid_from": None,
            "initial_label_valid_to": None,
        },
    )

    def find_locations(
        *,
        site_id=None,
        initial_label=None,
    ):
        assert site_id == 11
        assert initial_label == "tree_001"
        return (row,)

    monkeypatch.setattr(
        metadata,
        "find_locations",
        find_locations,
    )

    result, errors = resolve_location_selector(
        selector,
        source_path="updates.locations[0].update",
        existing_bindings=existing_bindings,
    )

    assert errors == ()
    assert result == row


def test_location_selector_reports_not_found(
    monkeypatch,
):
    selector = LocationLookupConfig(
        initial_label="missing",
    )

    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (),
    )

    row, errors = resolve_location_selector(
        selector,
        source_path="updates.locations[0].update",
    )

    assert row is None
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.NOT_FOUND
    assert errors[0].resource_type == "location"


def test_location_selector_reports_ambiguity(
    monkeypatch,
):
    selector = LocationLookupConfig(
        initial_label="tree_001",
    )

    monkeypatch.setattr(
        metadata,
        "find_locations",
        lambda **kwargs: (
            MetadataRow(71, {}),
            MetadataRow(72, {}),
        ),
    )

    row, errors = resolve_location_selector(
        selector,
        source_path="updates.locations[0].update",
    )

    assert row is None
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.AMBIGUOUS
    assert errors[0].candidate_ids == (71, 72)


def test_location_selector_missing_site_binding_is_invalid(
    monkeypatch,
):
    selector = LocationLookupConfig(
        site="sandhagen",
        initial_label="tree_001",
    )

    def fail_if_called(**kwargs):
        raise AssertionError(
            "find_locations should not be called "
            "when site cannot be resolved"
        )

    monkeypatch.setattr(
        metadata,
        "find_locations",
        fail_if_called,
    )

    row, errors = resolve_location_selector(
        selector,
        source_path="updates.locations[0].update",
        existing_bindings=(),
    )

    assert row is None
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.INVALID_REFERENCE
    assert errors[0].resource_type == "location"
    assert errors[0].source_path == (
        "updates.locations[0].update.site"
    )


def test_location_selector_planned_site_is_invalid(
    monkeypatch,
):
    selector = LocationLookupConfig(
        site="sandhagen",
        initial_label="tree_001",
    )

    existing_bindings = (
        PlanBinding(
            resource_type="sites",
            alias="sandhagen",
            resource=PlannedRef(
                resource_type="site",
                plan_id="sites[0]",
            ),
        ),
    )

    def fail_if_called(**kwargs):
        raise AssertionError(
            "find_locations should not be called "
            "with a planned site selector"
        )

    monkeypatch.setattr(
        metadata,
        "find_locations",
        fail_if_called,
    )

    row, errors = resolve_location_selector(
        selector,
        source_path="updates.locations[0].update",
        existing_bindings=existing_bindings,
    )

    assert row is None
    assert len(errors) == 1
    assert errors[0].code == PlanErrorCode.INVALID_REFERENCE
    assert errors[0].resource_type == "location"
    assert errors[0].source_path == (
        "updates.locations[0].update.site"
    )


