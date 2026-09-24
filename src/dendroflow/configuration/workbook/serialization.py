"""Serialize generated CONFIG models as validated, round-tripped YAML."""

from dataclasses import dataclass

import yaml
from pydantic import ValidationError

from ..models import ConfigModel
from ..validation import ConfigValidationError, validate_config


class WorkbookSerializationError(ValueError):
    """A generated CONFIG model could not be safely serialized to YAML."""


@dataclass(frozen=True)
class SerializedConfiguration:
    """YAML text and the validated model recovered by parsing that text."""

    yaml_text: str
    config: ConfigModel


def serialize_configuration(config: ConfigModel) -> SerializedConfiguration:
    """Return stable YAML and validate that it round-trips to the same model.

    The caller owns file output. Explicitly supplied ``None`` values are
    retained, which is required for nullable CONFIG update fields.
    """

    try:
        validate_config(config)
        payload = config.model_dump(mode="json", exclude_unset=True)
        yaml_text = yaml.safe_dump(
            payload,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        loaded = yaml.safe_load(yaml_text)
        round_tripped = ConfigModel.model_validate(loaded)
        validate_config(round_tripped)
    except (yaml.YAMLError, ValidationError, ConfigValidationError, TypeError, ValueError) as error:
        raise WorkbookSerializationError(
            f"configuration could not be serialized and validated: {error}"
        ) from error

    if round_tripped != config:
        raise WorkbookSerializationError(
            "configuration changed during YAML serialization round-trip"
        )

    return SerializedConfiguration(yaml_text=yaml_text, config=round_tripped)
