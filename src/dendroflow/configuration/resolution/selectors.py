from .. import metadata
from ..metadata import MetadataRow
from ..models import (
    DeploymentLookupConfig,
    SensorLookupConfig,
)
from ..plan import (
    PlanBinding,
    PlanError,
    PlanErrorCode,
    PlannedRef,
)
from .common import _find_binding


def resolve_sensor_selector(
    selector: SensorLookupConfig,
    *,
    source_path: str,
    existing_bindings: tuple[PlanBinding, ...] = (),
) -> tuple[MetadataRow | None, tuple[PlanError, ...]]:
    """Resolve a sensor selector to exactly one existing sensor."""

    sensor_model_id: int | None = None

    if selector.sensor_model is not None:
        binding = _find_binding(
            existing_bindings,
            "sensor_models",
            selector.sensor_model,
        )

        if binding is None:
            return None, (
                PlanError(
                    code=PlanErrorCode.INVALID_REFERENCE,
                    resource_type="sensor",
                    source_path=f"{source_path}.sensor_model",
                    message=(
                        "unable to resolve sensor model "
                        f"{selector.sensor_model!r}"
                    ),
                ),
            )

        if isinstance(binding.resource, PlannedRef):
            return None, (
                PlanError(
                    code=PlanErrorCode.INVALID_REFERENCE,
                    resource_type="sensor",
                    source_path=f"{source_path}.sensor_model",
                    message=(
                        "existing sensor selector cannot use "
                        "a sensor model planned for creation"
                    ),
                ),
            )

        sensor_model_id = binding.resource.database_id

    rows = metadata.find_sensors(
        serial_number=selector.serial_number,
        sensor_model_id=sensor_model_id,
    )

    if not rows:
        return None, (
            PlanError(
                code=PlanErrorCode.NOT_FOUND,
                resource_type="sensor",
                source_path=source_path,
                message="sensor resource not found",
            ),
        )

    if len(rows) > 1:
        return None, (
            PlanError(
                code=PlanErrorCode.AMBIGUOUS,
                resource_type="sensor",
                source_path=source_path,
                message="sensor selector matched multiple resources",
                candidate_ids=tuple(
                    row.database_id for row in rows
                ),
            ),
        )

    return rows[0], ()


def resolve_deployment_selector(
    selector: DeploymentLookupConfig,
    *,
    source_path: str,
    existing_bindings: tuple[PlanBinding, ...] = (),
) -> tuple[MetadataRow | None, tuple[PlanError, ...]]:
    """Resolve a deployment selector to exactly one existing deployment."""

    relationship_ids: dict[str, int | None] = {
        "sensor": None,
        "location": None,
        "variable": None,
    }

    resource_types = {
        "sensor": "sensors",
        "location": "locations",
        "variable": "variables",
    }

    for field, resource_type in resource_types.items():
        alias = getattr(selector, field)

        if alias is None:
            continue

        binding = _find_binding(
            existing_bindings,
            resource_type,
            alias,
        )

        if binding is None:
            return None, (
                PlanError(
                    code=PlanErrorCode.INVALID_REFERENCE,
                    resource_type="deployment",
                    source_path=f"{source_path}.{field}",
                    message=(
                        f"unable to resolve {field} {alias!r}"
                    ),
                ),
            )

        if isinstance(binding.resource, PlannedRef):
            return None, (
                PlanError(
                    code=PlanErrorCode.INVALID_REFERENCE,
                    resource_type="deployment",
                    source_path=f"{source_path}.{field}",
                    message=(
                        "existing deployment selector cannot use "
                        f"a {field} planned for creation"
                    ),
                ),
            )

        relationship_ids[field] = (
            binding.resource.database_id
        )

    rows = metadata.find_deployments(
        sensor_id=relationship_ids["sensor"],
        location_id=relationship_ids["location"],
        variable_id=relationship_ids["variable"],
        valid_from=selector.valid_from,
    )

    if not rows:
        return None, (
            PlanError(
                code=PlanErrorCode.NOT_FOUND,
                resource_type="deployment",
                source_path=source_path,
                message="deployment resource not found",
            ),
        )

    if len(rows) > 1:
        return None, (
            PlanError(
                code=PlanErrorCode.AMBIGUOUS,
                resource_type="deployment",
                source_path=source_path,
                message=(
                    "deployment selector matched "
                    "multiple resources"
                ),
                candidate_ids=tuple(
                    row.database_id for row in rows
                ),
            ),
        )

    return rows[0], ()


