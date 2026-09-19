import runpy
import sys
from pathlib import Path

import psycopg
import pytest

from dendroflow.cli.main import main


@pytest.fixture(autouse=True)
def block_database_access(monkeypatch):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("Validation must not connect to PostgreSQL")

    monkeypatch.setattr(psycopg, "connect", unexpected_connection)


def write_config(tmp_path, content):
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def assert_invalid(path, capsys, *messages):
    assert main(["config", "validate", str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"Configuration validation failed: {path}" in captured.err
    for message in messages:
        assert message in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "content",
    [
        "{}",
        "sites:\n  - site_code: station\n    name: Station\n",
    ],
)
def test_validate_accepts_valid_configuration(content, tmp_path, capsys):
    path = write_config(tmp_path, content)

    assert main(["config", "validate", str(path)]) == 0
    captured = capsys.readouterr()
    assert captured.out == (
        f"Configuration valid: {path}\n"
        "Database state was not checked.\n"
    )
    assert captured.err == ""


def test_validate_accepts_sandhagen_fixture(capsys):
    path = Path(__file__).parent / "data" / "sandhagen_config.yaml"

    assert main(["config", "validate", str(path)]) == 0
    captured = capsys.readouterr()
    assert "Configuration valid:" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("use_directory", [False, True])
def test_validate_reports_unreadable_path(use_directory, tmp_path, capsys):
    path = tmp_path if use_directory else tmp_path / "missing.yaml"

    assert_invalid(path, capsys, "unable to read configuration file")


def test_validate_reports_permission_error(monkeypatch, tmp_path, capsys):
    path = tmp_path / "denied.yaml"

    def deny_read(self, *args, **kwargs):
        raise PermissionError("permission denied")

    monkeypatch.setattr(Path, "read_text", deny_read)

    assert_invalid(path, capsys, "unable to read configuration file")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("sites: [", "invalid YAML"),
        ("", "configuration root must be a YAML mapping"),
        ("- station\n", "configuration root must be a YAML mapping"),
    ],
)
def test_validate_reports_yaml_errors(content, message, tmp_path, capsys):
    path = write_config(tmp_path, content)

    assert_invalid(path, capsys, message)


def test_validate_reports_invalid_utf8(tmp_path, capsys):
    path = tmp_path / "config.yaml"
    path.write_bytes(b"\xff")

    assert_invalid(path, capsys, "configuration file must be UTF-8")


def test_validate_reports_all_model_errors(tmp_path, capsys):
    path = write_config(
        tmp_path,
        "sites:\n  - site_code: station\nvariables:\n  - variable: ''\n",
    )

    assert_invalid(
        path,
        capsys,
        "sites[0].name:",
        "variables[0].variable:",
    )


def test_validate_reports_unknown_field(tmp_path, capsys):
    path = write_config(tmp_path, "unexpected: true\n")

    assert_invalid(path, capsys, "unexpected:", "Extra inputs")


def test_validate_reports_model_level_error(tmp_path, capsys):
    path = write_config(
        tmp_path,
        "sites:\n  - site_code: station\n    name: Station\n"
        "    latitude: 54.0\n",
    )

    assert_invalid(path, capsys, "sites[0]:", "latitude and longitude")


def test_validate_reports_all_semantic_errors(tmp_path, capsys):
    path = write_config(
        tmp_path,
        "variables:\n  - variable: temperature\n"
        "  - variable: temperature\n"
        "sensors:\n  - serial_number: A123\n"
        "    sensor_model: missing_model\n",
    )

    assert_invalid(
        path,
        capsys,
        "variables[1]:",
        "duplicate natural identity",
        "sensors[0].sensor_model:",
        "unknown sensor_models reference: missing_model",
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["config", "--help"],
        ["config", "validate", "--help"],
    ],
)
def test_config_help(argv, capsys):
    with pytest.raises(SystemExit) as caught:
        main(argv)

    assert caught.value.code == 0
    captured = capsys.readouterr()
    assert "validate" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    "argv",
    [
        ["config"],
        ["config", "validate"],
        ["config", "validate", "config.yaml", "--unknown"],
    ],
)
def test_config_usage_errors(argv, capsys):
    with pytest.raises(SystemExit) as caught:
        main(argv)

    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage:" in captured.err


def test_module_entry_point_propagates_validation_failure(
    tmp_path,
    monkeypatch,
    capsys,
):
    path = write_config(tmp_path, "sites: [")
    monkeypatch.setattr(
        sys,
        "argv",
        ["dendroflow", "config", "validate", str(path)],
    )

    with pytest.raises(SystemExit) as caught:
        runpy.run_module("dendroflow", run_name="__main__")

    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid YAML" in captured.err
