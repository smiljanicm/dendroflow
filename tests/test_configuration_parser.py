from pathlib import Path

import pytest
from pydantic import ValidationError

from dendroflow.configuration import ConfigParseError, load_config, validate_config


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_config_reads_valid_yaml(tmp_path):
    path = write_config(
        tmp_path,
        """
sites:
  - site_code: sandhagen_rewetted
    name: Sandhagen Rewetted
""",
    )

    config = load_config(path)

    assert len(config.sites) == 1
    assert config.sites[0].site_code == "sandhagen_rewetted"


def test_load_config_accepts_string_path(tmp_path):
    path = write_config(
        tmp_path,
        """
variables:
  - variable: water_level
""",
    )

    config = load_config(str(path))

    assert config.variables[0].variable == "water_level"


def test_load_config_rejects_missing_file(tmp_path):
    path = tmp_path / "missing.yaml"

    with pytest.raises(
        ConfigParseError,
        match="unable to read configuration file",
    ):
        load_config(path)


def test_load_config_rejects_malformed_yaml(tmp_path):
    path = write_config(
        tmp_path,
        """
sites:
  - site_code: sandhagen
    name: [
""",
    )

    with pytest.raises(
        ConfigParseError,
        match="invalid YAML",
    ):
        load_config(path)


def test_load_config_rejects_non_mapping_root(tmp_path):
    path = write_config(
        tmp_path,
        """
- sandhagen
- water_level
""",
    )

    with pytest.raises(
        ConfigParseError,
        match="configuration root must be a YAML mapping",
    ):
        load_config(path)


def test_load_config_preserves_model_validation_errors(tmp_path):
    path = write_config(
        tmp_path,
        """
variables:
  - variable: ""
""",
    )

    with pytest.raises(ValidationError):
        load_config(path)


def test_load_config_rejects_empty_file(tmp_path):
    path = write_config(tmp_path, "")

    with pytest.raises(
        ConfigParseError,
        match="configuration root must be a YAML mapping",
    ):
        load_config(path)


def test_load_and_validate_sandhagen_config():
    path = Path("tests/data/sandhagen_config.yaml")

    config = load_config(path)
    validate_config(config)

    assert len(config.sites) == 1
    assert len(config.sensors) == 1
    assert len(config.deployments) == 2
    assert len(config.files) == 1
    assert len(config.files[0].interfaces) == 2

    assert config.files[0].timestamp.timezone == "Etc/GMT-1"
    assert config.files[0].reader.options["skiprows"] == [0, 2, 3]

