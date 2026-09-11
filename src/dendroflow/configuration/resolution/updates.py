from ..models import ConfigModel
from ..plan import (
    ExistingRef,
    FieldChange,
    PlanAction,
    PlanBinding,
    PlanError,
    ResolvedPlanItem,
    ResolvedSensorValues,
)
from .selectors import resolve_sensor_selector


def resolve_sensor_updates(
    config: ConfigModel,
    existing_bindings: tuple[PlanBinding, ...] = (),
) -> tuple[
    tuple[ResolvedPlanItem, ...],
    tuple[PlanError, ...],
]:
    """Resolve explicit sensor updates."""

    items: list[ResolvedPlanItem] = []
    errors: list[PlanError] = []

    for index, update_config in enumerate(
        config.updates.sensors
    ):
        source_path = f"updates.sensors[{index}]"

        row, selector_errors = resolve_sensor_selector(
            update_config.update,
            source_path=f"{source_path}.update",
            existing_bindings=existing_bindings,
        )

        if selector_errors:
            errors.extend(selector_errors)
            continue

        assert row is not None

        changes: list[FieldChange] = []

        serial_number = row.values["serial_number"]
        description = row.values["description"]

        fields_set = update_config.set.model_fields_set

        if "serial_number" in fields_set:
            requested_serial_number = (
                update_config.set.serial_number
            )

            if requested_serial_number != serial_number:
                changes.append(
                    FieldChange(
                        field="serial_number",
                        before=serial_number,
                        after=requested_serial_number,
                        identity_change=True,
                    )
                )
                serial_number = requested_serial_number

        if "description" in fields_set:
            requested_description = (
                update_config.set.description
            )

            if requested_description != description:
                changes.append(
                    FieldChange(
                        field="description",
                        before=description,
                        after=requested_description,
                        identity_change=False,
                    )
                )
                description = requested_description

        if not changes:
            continue

        sensor_model_id = row.values["sensor_model_id"]

        items.append(
            ResolvedPlanItem(
                plan_id=source_path,
                resource_type="sensor",
                action=PlanAction.UPDATE,
                database_id=row.database_id,
                values=ResolvedSensorValues(
                    serial_number=serial_number,
                    sensor_model=ExistingRef(
                        resource_type="sensor_model",
                        database_id=sensor_model_id,
                    ),
                    description=description,
                ),
                changes=tuple(changes),
                source_path=source_path,
            )
        )

    return tuple(items), tuple(errors)