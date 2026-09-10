from dataclasses import dataclass

from .models import ConfigModel, LookupConfig


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


