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

