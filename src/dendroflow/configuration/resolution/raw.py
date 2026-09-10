from .. import raw
from ..models import ConfigModel, FileConfig
from ..plan import (
    ExistingRef,
    PlanAction,
    PlanBinding,
    PlanError,
    PlannedRef,
    ResolvedFileValues,
    ResolvedPlanItem,
    ResourceRef,
)
from .common import _conflict


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


def _build_reader_config(file_config: FileConfig) -> dict[str, object]:
    return {
        "reader": file_config.reader.type,
        "options": file_config.reader.options,
    }
