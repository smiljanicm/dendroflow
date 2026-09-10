from datetime import datetime

from ..metadata import MetadataRow
from ..plan import (
    PlanBinding,
    PlanError,
    PlanErrorCode,
)


def _find_binding(
    bindings: tuple[PlanBinding, ...],
    resource_type: str,
    alias: str,
) -> PlanBinding | None:
    for binding in bindings:
        if (
            binding.resource_type == resource_type
            and binding.alias == alias
        ):
            return binding

    return None


def _compare_explicit_fields(
    declaration: object,
    row: MetadataRow,
    fields: tuple[str, ...],
    source_path: str,
    resource_type: str,
) -> tuple[PlanError, ...]:
    errors: list[PlanError] = []

    for field in fields:
        if field not in declaration.model_fields_set:
            continue

        requested = getattr(declaration, field)
        existing = row.values[field]

        if requested != existing:
            errors.append(
                _conflict(
                    source_path,
                    resource_type,
                    field,
                    existing,
                    requested,
                )
            )

    return tuple(errors)


def _conflict(
    source_path: str,
    resource_type: str,
    field: str,
    existing: object,
    requested: object,
) -> PlanError:
    return PlanError(
        code=PlanErrorCode.CONFLICT,
        resource_type=resource_type,
        source_path=f"{source_path}.{field}",
        message=(
            f"{field} differs from existing resource: "
            f"existing={existing!r}, requested={requested!r}"
        ),
    )


def _intervals_overlap(
    first_start: datetime,
    first_end: datetime | None,
    second_start: datetime,
    second_end: datetime | None,
) -> bool:
    """Return whether two half-open time intervals overlap."""

    return (
        first_end is None or second_start < first_end
    ) and (
        second_end is None or first_start < second_end
    )


