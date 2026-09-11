from .. import raw
from ..models import ConfigModel, FileConfig
from ..plan import (
    ExistingRef,
    PlanAction,
    PlanBinding,
    PlanError,
    PlanErrorCode,
    PlannedRef,
    ResolvedFileValues,
    ResolvedInterfaceValues,
    ResolvedPlanItem,
    ResourceRef,
)
from .common import (
    _conflict,
    _find_binding,
)


def resolve_file_declarations(
    config: ConfigModel,
) -> tuple[
    tuple[ResolvedPlanItem, ...],
    tuple[PlanBinding, ...],
    tuple[PlanError, ...],
]:
    """Resolve configured RAW files."""

    items: list[ResolvedPlanItem] = []
    bindings: list[PlanBinding] = []
    errors: list[PlanError] = []

    for index, declaration in enumerate(config.files):
        plan_id = f"files[{index}]"

        reader_config = _build_reader_config(declaration)

        row = raw.find_file(declaration.path)

        if row is None:
            values = ResolvedFileValues(
                filepath=declaration.path,
                timestamp_timezone=declaration.timestamp.timezone,
                timestamp_format=declaration.timestamp.format,
                reader_config=reader_config,
            )

            item = ResolvedPlanItem(
                plan_id=plan_id,
                resource_type="file",
                action=PlanAction.CREATE,
                values=values,
                source_path=plan_id,
            )

            resource: ResourceRef = PlannedRef(
                resource_type="file",
                plan_id=plan_id,
            )

        else:
            if (
                row.values["timestamp_timezone"]
                != declaration.timestamp.timezone
            ):
                errors.append(
                    _conflict(
                        plan_id,
                        "file",
                        "timestamp_timezone",
                        row.values["timestamp_timezone"],
                        declaration.timestamp.timezone,
                    )
                )

            if (
                row.values["timestamp_format"]
                != declaration.timestamp.format
            ):
                errors.append(
                    _conflict(
                        plan_id,
                        "file",
                        "timestamp_format",
                        row.values["timestamp_format"],
                        declaration.timestamp.format,
                    )
                )

            if row.values["reader_config"] != reader_config:
                errors.append(
                    _conflict(
                        plan_id,
                        "file",
                        "reader_config",
                        row.values["reader_config"],
                        reader_config,
                    )
                )

            values = ResolvedFileValues(
                filepath=row.values["filepath"],
                timestamp_timezone=row.values[
                    "timestamp_timezone"
                ],
                timestamp_format=row.values[
                    "timestamp_format"
                ],
                reader_config=row.values["reader_config"],
            )

            item = ResolvedPlanItem(
                plan_id=plan_id,
                resource_type="file",
                action=PlanAction.REUSE,
                database_id=row.database_id,
                values=values,
                source_path=plan_id,
            )

            resource = ExistingRef(
                resource_type="file",
                database_id=row.database_id,
            )

        items.append(item)

        if declaration.ref is not None:
            bindings.append(
                PlanBinding(
                    resource_type="files",
                    alias=declaration.ref,
                    resource=resource,
                )
            )

    return tuple(items), tuple(bindings), tuple(errors)


def resolve_interface_declarations(
    config: ConfigModel,
    file_items: tuple[ResolvedPlanItem, ...],
    existing_bindings: tuple[PlanBinding, ...] = (),
) -> tuple[
    tuple[ResolvedPlanItem, ...],
    tuple[PlanError, ...],
]:
    """Resolve configured RAW file interfaces."""

    items: list[ResolvedPlanItem] = []
    errors: list[PlanError] = []

    file_items_by_plan_id = {
        item.plan_id: item
        for item in file_items
        if item.resource_type == "file"
    }

    for file_index, file_declaration in enumerate(config.files):
        file_plan_id = f"files[{file_index}]"
        file_item = file_items_by_plan_id.get(file_plan_id)

        if file_item is None:
            continue

        if file_item.action == PlanAction.CREATE:
            file_ref: ResourceRef = PlannedRef(
                resource_type="file",
                plan_id=file_item.plan_id,
            )
            existing_interfaces = ()
        else:
            assert file_item.database_id is not None

            file_ref = ExistingRef(
                resource_type="file",
                database_id=file_item.database_id,
            )
            existing_interfaces = raw.find_file_interfaces(
                file_item.database_id
            )

        for interface_index, declaration in enumerate(
            file_declaration.interfaces
        ):
            plan_id = (
                f"{file_plan_id}.interfaces[{interface_index}]"
            )

            deployment_binding = _find_binding(
                existing_bindings,
                "deployments",
                declaration.deployment,
            )

            if deployment_binding is None:
                errors.append(
                    PlanError(
                        code=PlanErrorCode.INVALID_REFERENCE,
                        resource_type="interface",
                        source_path=f"{plan_id}.deployment",
                        message=(
                            "unable to resolve deployment "
                            f"{declaration.deployment!r}"
                        ),
                    )
                )
                continue

            requested_deployment = deployment_binding.resource

            matching_row = next(
                (
                    row
                    for row in existing_interfaces
                    if row.values["values_column"]
                    == declaration.values_column
                ),
                None,
            )

            if matching_row is None:
                items.append(
                    ResolvedPlanItem(
                        plan_id=plan_id,
                        resource_type="interface",
                        action=PlanAction.CREATE,
                        values=ResolvedInterfaceValues(
                            file=file_ref,
                            deployment=requested_deployment,
                            values_column=declaration.values_column,
                            timestamp_column=(
                                declaration.timestamp_column
                            ),
                            unit=declaration.unit,
                        ),
                        source_path=plan_id,
                    )
                )
                continue

            existing_deployment = ExistingRef(
                resource_type="deployment",
                database_id=matching_row.values[
                    "deployment_id"
                ],
            )

            if requested_deployment != existing_deployment:
                errors.append(
                    _conflict(
                        plan_id,
                        "interface",
                        "deployment",
                        existing_deployment,
                        requested_deployment,
                    )
                )

            if (
                matching_row.values["timestamp_column"]
                != declaration.timestamp_column
            ):
                errors.append(
                    _conflict(
                        plan_id,
                        "interface",
                        "timestamp_column",
                        matching_row.values[
                            "timestamp_column"
                        ],
                        declaration.timestamp_column,
                    )
                )

            if matching_row.values["unit"] != declaration.unit:
                errors.append(
                    _conflict(
                        plan_id,
                        "interface",
                        "unit",
                        matching_row.values["unit"],
                        declaration.unit,
                    )
                )

            items.append(
                ResolvedPlanItem(
                    plan_id=plan_id,
                    resource_type="interface",
                    action=PlanAction.REUSE,
                    database_id=matching_row.database_id,
                    values=ResolvedInterfaceValues(
                        file=file_ref,
                        deployment=existing_deployment,
                        values_column=matching_row.values[
                            "values_column"
                        ],
                        timestamp_column=matching_row.values[
                            "timestamp_column"
                        ],
                        unit=matching_row.values["unit"],
                    ),
                    source_path=plan_id,
                )
            )

    return tuple(items), tuple(errors)


def _build_reader_config(file_config: FileConfig) -> dict[str, object]:
    return {
        "reader": file_config.reader.type,
        "options": file_config.reader.options,
    }

