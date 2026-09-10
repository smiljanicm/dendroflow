from collections.abc import Callable
from dataclasses import dataclass

from . import metadata
from .metadata import MetadataRow
from .models import ConfigModel, LookupConfig
from .plan import (
    ExistingRef,
    PlanBinding,
    PlanError,
    PlanErrorCode,
)


@dataclass(frozen=True)
class DeclarationAlias:
    """Alias referring to a resource declaration in this configuration."""

    resource_type: str
    alias: str
    source_path: str
    declaration_index: int


@dataclass(frozen=True)
class ReferenceAlias:
    """Alias referring to an existing-resource lookup."""

    resource_type: str
    alias: str
    source_path: str
    selector: LookupConfig


LocalAlias = DeclarationAlias | ReferenceAlias


@dataclass(frozen=True)
class AliasRegistry:
    """Local YAML namespace used during configuration resolution."""

    entries: tuple[LocalAlias, ...] = ()

    def get(
        self,
        resource_type: str,
        alias: str,
    ) -> LocalAlias | None:
        for entry in self.entries:
            if (
                entry.resource_type == resource_type
                and entry.alias == alias
            ):
                return entry

        return None

    def aliases(self, resource_type: str) -> tuple[str, ...]:
        return tuple(
            entry.alias
            for entry in self.entries
            if entry.resource_type == resource_type
        )


def build_alias_registry(config: ConfigModel) -> AliasRegistry:
    """Build the local alias namespace for a validated configuration."""

    entries: list[LocalAlias] = []

    resource_types = (
        "sites",
        "location_types",
        "sensor_types",
        "variables",
        "sensor_models",
        "sensors",
        "locations",
        "deployments",
        "files",
    )

    for resource_type in resource_types:
        declarations = getattr(config, resource_type)

        for index, declaration in enumerate(declarations):
            if declaration.ref is None:
                continue

            entries.append(
                DeclarationAlias(
                    resource_type=resource_type,
                    alias=declaration.ref,
                    source_path=f"{resource_type}[{index}].ref",
                    declaration_index=index,
                )
            )

        references = getattr(config.references, resource_type)

        for alias in sorted(references):
            entries.append(
                ReferenceAlias(
                    resource_type=resource_type,
                    alias=alias,
                    source_path=(
                        f"references.{resource_type}.{alias}"
                    ),
                    selector=references[alias],
                )
            )

    return AliasRegistry(entries=tuple(entries))


SimpleMetadataFinder = Callable[[str], MetadataRow | None]


_SIMPLE_REFERENCE_RESOLVERS: dict[
    str,
    tuple[str, SimpleMetadataFinder],
] = {
    "sites": ("site_code", metadata.find_site),
    "location_types": ("type", metadata.find_location_type),
    "sensor_types": ("type", metadata.find_sensor_type),
    "variables": ("variable", metadata.find_variable),
}


def resolve_simple_reference_aliases(
    registry: AliasRegistry,
) -> tuple[tuple[PlanBinding, ...], tuple[PlanError, ...]]:
    """Resolve simple METADATA reference aliases against PostgreSQL."""

    bindings: list[PlanBinding] = []
    errors: list[PlanError] = []

    for entry in registry.entries:
        if not isinstance(entry, ReferenceAlias):
            continue

        selector_field = _SIMPLE_REFERENCE_FIELDS.get(
            entry.resource_type
        )

        if selector_field is None:
            continue

        selector_value = getattr(entry.selector, selector_field)

        if selector_value is None:
            errors.append(
                PlanError(
                    code=PlanErrorCode.INVALID_REFERENCE,
                    resource_type=entry.resource_type,
                    source_path=entry.source_path,
                    message=(
                        f"{entry.resource_type} reference must specify "
                        f"{selector_field}"
                    ),
                )
            )
            continue

        row = _find_simple_metadata(
            entry.resource_type,
            selector_value,
        )

        if row is None:
            errors.append(
                PlanError(
                    code=PlanErrorCode.NOT_FOUND,
                    resource_type=entry.resource_type,
                    source_path=entry.source_path,
                    message=(
                        f"{entry.resource_type} resource not found "
                        f"for {selector_field}={selector_value!r}"
                    ),
                )
            )
            continue

        bindings.append(
            PlanBinding(
                resource_type=entry.resource_type,
                alias=entry.alias,
                resource=ExistingRef(
                    resource_type=_singular_resource_type(
                        entry.resource_type
                    ),
                    database_id=row.database_id,
                ),
            )
        )

    return tuple(bindings), tuple(errors)


def _singular_resource_type(resource_type: str) -> str:
    names = {
        "sites": "site",
        "location_types": "location_type",
        "sensor_types": "sensor_type",
        "variables": "variable",
    }

    return names[resource_type]


_SIMPLE_REFERENCE_FIELDS = {
    "sites": "site_code",
    "location_types": "type",
    "sensor_types": "type",
    "variables": "variable",
}


def _find_simple_metadata(
    resource_type: str,
    value: str,
) -> MetadataRow | None:
    if resource_type == "sites":
        return metadata.find_site(value)

    if resource_type == "location_types":
        return metadata.find_location_type(value)

    if resource_type == "sensor_types":
        return metadata.find_sensor_type(value)

    if resource_type == "variables":
        return metadata.find_variable(value)

    raise ValueError(
        f"unsupported simple metadata resource type: {resource_type}"
    )


