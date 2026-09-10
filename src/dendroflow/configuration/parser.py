from pathlib import Path

import yaml

from .models import ConfigModel


class ConfigParseError(ValueError):
    """Raised when a configuration file cannot be parsed as YAML."""


def load_config(path: str | Path) -> ConfigModel:
    """Load and validate a DendroFlow YAML configuration file."""

    config_path = Path(path)

    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigParseError(
            f"unable to read configuration file: {config_path}"
        ) from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigParseError(
            f"invalid YAML in configuration file: {config_path}"
        ) from exc

    if not isinstance(data, dict):
        raise ConfigParseError(
            "configuration root must be a YAML mapping"
        )

    return ConfigModel.model_validate(data)