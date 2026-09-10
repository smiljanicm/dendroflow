from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from typing import Any

from .models import ConfigModel


@dataclass(frozen=True)
class ConfigValidationIssue:
    path: str
    message: str


class ConfigValidationError(ValueError):
    """Raised when a configuration is internally inconsistent."""

    def __init__(self, issues: Sequence[ConfigValidationIssue]) -> None:
        self.issues = tuple(issues)

        message = "configuration validation failed:\n" + "\n".join(
            f"- {issue.path}: {issue.message}"
            for issue in self.issues
        )
        super().__init__(message)


def validate_config(config: ConfigModel) -> None:
    """Validate consistency across a complete configuration."""

    issues = collect_config_issues(config)

    if issues:
        raise ConfigValidationError(issues)


def collect_config_issues(
    config: ConfigModel,
) -> tuple[ConfigValidationIssue, ...]:
    """Return all whole-configuration validation issues."""

    issues: list[ConfigValidationIssue] = []

    _validate_refs(config, issues)
    _validate_natural_identities(config, issues)
    _validate_relationships(config, issues)

    return tuple(issues)


def _validate_refs(
    config: ConfigModel,
    issues: list[ConfigValidationIssue],
) -> None:
    resource_sections = {
        "sites": config.sites,
        "location_types": config.location_types,
        "sensor_types": config.sensor_types,
        "variables": config.variables,
        "sensor_models": config.sensor_models,
        "sensors": config.sensors,
        "locations": config.locations,
        "deployments": config.deployments,
        "files": config.files,
    }

    for resource_type, resources in resource_sections.items():
        seen: set[str] = set()

        for index, resource in enumerate(resources):
            ref = getattr(resource, "ref", None)

            if ref is None:
                continue

            if ref in seen:
                issues.append(
                    ConfigValidationIssue(
                        path=f"{resource_type}[{index}].ref",
                        message=f"duplicate {resource_type} ref: {ref}",
                    )
                )
            else:
                seen.add(ref)

        reference_aliases = set(
            getattr(config.references, resource_type).keys()
        )

        for alias in sorted(seen & reference_aliases):
            issues.append(
                ConfigValidationIssue(
                    path=f"references.{resource_type}.{alias}",
                    message=(
                        f"{resource_type} alias {alias!r} is also used "
                        "by a declaration ref"
                    ),
                )
            )


def _validate_natural_identities(
    config: ConfigModel,
    issues: list[ConfigValidationIssue],
) -> None:
    _find_duplicate_identities(
        config.sites,
        "sites",
        lambda item: item.site_code,
        "site_code",
        issues,
    )
    _find_duplicate_identities(
        config.location_types,
        "location_types",
        lambda item: item.type,
        "type",
        issues,
    )
    _find_duplicate_identities(
        config.sensor_types,
        "sensor_types",
        lambda item: item.type,
        "type",
        issues,
    )
    _find_duplicate_identities(
        config.variables,
        "variables",
        lambda item: item.variable,
        "variable",
        issues,
    )
    _find_duplicate_identities(
        config.sensor_models,
        "sensor_models",
        lambda item: (item.manufacturer, item.model),
        "manufacturer + model",
        issues,
    )
    _find_duplicate_identities(
        config.sensors,
        "sensors",
        lambda item: item.serial_number,
        "serial_number",
        issues,
    )
    _find_duplicate_identities(
        config.locations,
        "locations",
        lambda item: (item.site, item.initial_label.label),
        "site + initial_label",
        issues,
    )
    _find_duplicate_identities(
        config.deployments,
        "deployments",
        lambda item: (
            item.sensor,
            item.location,
            item.variable,
            item.valid_from,
        ),
        "sensor + location + variable + valid_from",
        issues,
    )
    _find_duplicate_identities(
        config.files,
        "files",
        lambda item: item.path,
        "path",
        issues,
    )


def _validate_relationships(
    config: ConfigModel,
    issues: list[ConfigValidationIssue],
) -> None:
    aliases = {
        resource_type: _get_local_aliases(config, resource_type)
        for resource_type in (
            "sites",
            "location_types",
            "sensor_types",
            "variables",
            "sensor_models",
            "sensors",
            "locations",
            "deployments",
        )
    }

    for index, site in enumerate(config.sites):
        if site.parent is not None:
            _require_local_alias(
                site.parent,
                "sites",
                f"sites[{index}].parent",
                aliases,
                issues,
            )

    for index, sensor_model in enumerate(config.sensor_models):
        _require_local_alias(
            sensor_model.sensor_type,
            "sensor_types",
            f"sensor_models[{index}].sensor_type",
            aliases,
            issues,
        )

    for index, sensor in enumerate(config.sensors):
        _require_local_alias(
            sensor.sensor_model,
            "sensor_models",
            f"sensors[{index}].sensor_model",
            aliases,
            issues,
        )

    for index, location in enumerate(config.locations):
        _require_local_alias(
            location.site,
            "sites",
            f"locations[{index}].site",
            aliases,
            issues,
        )
        _require_local_alias(
            location.location_type,
            "location_types",
            f"locations[{index}].location_type",
            aliases,
            issues,
        )

    for index, location_label in enumerate(config.location_labels):
        _require_local_alias(
            location_label.location,
            "locations",
            f"location_labels[{index}].location",
            aliases,
            issues,
        )

    for index, deployment in enumerate(config.deployments):
        _require_local_alias(
            deployment.sensor,
            "sensors",
            f"deployments[{index}].sensor",
            aliases,
            issues,
        )
        _require_local_alias(
            deployment.location,
            "locations",
            f"deployments[{index}].location",
            aliases,
            issues,
        )
        _require_local_alias(
            deployment.variable,
            "variables",
            f"deployments[{index}].variable",
            aliases,
            issues,
        )

    for file_index, file in enumerate(config.files):
        for interface_index, interface in enumerate(file.interfaces):
            _require_local_alias(
                interface.deployment,
                "deployments",
                (
                    f"files[{file_index}].interfaces"
                    f"[{interface_index}].deployment"
                ),
                aliases,
                issues,
            )


def _find_duplicate_identities(
    resources: Sequence[Any],
    resource_type: str,
    identity: Callable[[Any], Hashable],
    identity_name: str,
    issues: list[ConfigValidationIssue],
) -> None:
    seen: dict[Hashable, int] = {}

    for index, resource in enumerate(resources):
        key = identity(resource)

        if key in seen:
            first_index = seen[key]
            issues.append(
                ConfigValidationIssue(
                    path=f"{resource_type}[{index}]",
                    message=(
                        f"duplicate natural identity "
                        f"({identity_name}); first declared at "
                        f"{resource_type}[{first_index}]"
                    ),
                )
            )
        else:
            seen[key] = index


def _get_local_aliases(
    config: ConfigModel,
    resource_type: str,
) -> set[str]:
    resources = getattr(config, resource_type)

    declaration_refs = {
        resource.ref
        for resource in resources
        if getattr(resource, "ref", None) is not None
    }

    reference_aliases = set(
        getattr(config.references, resource_type).keys()
    )

    return declaration_refs | reference_aliases


def _require_local_alias(
    value: str,
    resource_type: str,
    path: str,
    aliases: dict[str, set[str]],
    issues: list[ConfigValidationIssue],
) -> None:
    if value not in aliases[resource_type]:
        issues.append(
            ConfigValidationIssue(
                path=path,
                message=(
                    f"unknown {resource_type} reference: {value}"
                ),
            )
        )