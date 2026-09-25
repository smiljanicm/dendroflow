import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

DEFAULT_TARGET_ENVIRONMENT = "local"


def load_env(path: Path) -> dict[str, str]:
    """Load simple KEY=VALUE pairs from a .env file."""
    values: dict[str, str] = {}

    if not path.exists():
        return values

    for line in path.read_text().splitlines():
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        key, separator, value = line.partition("=")

        if not separator:
            continue

        values[key.strip()] = value.strip()

    return values


def get_connection_parameters() -> dict[str, str]:
    """Return PostgreSQL connection parameters.

    Environment variables take precedence. If they are not set,
    values are loaded from the project's .env file.
    """
    project_root = Path(__file__).resolve().parents[2]
    env_file = project_root / ".env"

    env = load_env(env_file)

    def get_value(name: str, default: str | None = None) -> str:
        value = os.getenv(name)

        if value is not None:
            return value

        if name in env:
            return env[name]

        if default is not None:
            return default

        raise RuntimeError(
            f"Missing required environment variable: {name}"
        )

    return {
        "host": get_value("POSTGRES_HOST", "localhost"),
        "port": get_value("POSTGRES_PORT", "5432"),
        "user": get_value("POSTGRES_USER"),
        "password": get_value("POSTGRES_PASSWORD"),
    }


@dataclass(frozen=True)
class DatabaseTarget:
    """One invocation's environment label and PostgreSQL settings."""

    environment: str
    connection_parameters: Mapping[str, str] = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "connection_parameters",
            MappingProxyType(dict(self.connection_parameters)),
        )


def _configured_values() -> tuple[dict[str, str], dict[str, str]]:
    project_root = Path(__file__).resolve().parents[2]
    return dict(os.environ), load_env(project_root / ".env")


def _read_value(
    process_values: Mapping[str, str],
    file_values: Mapping[str, str],
    name: str,
    default: str | None = None,
) -> str:
    if name in process_values:
        return process_values[name]
    if name in file_values:
        return file_values[name]
    if default is not None:
        return default
    raise RuntimeError(f"Missing required environment variable: {name}")


def _validate_environment_label(value: str) -> str:
    if (
        not value
        or len(value) > 128
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise RuntimeError(
            "DENDROFLOW_ENVIRONMENT must contain 1-128 characters, "
            "with no surrounding whitespace or control characters"
        )
    return value


def get_target_environment() -> str:
    """Return the non-secret database-pair label, defaulting to local."""
    process_values, file_values = _configured_values()
    value = _read_value(
        process_values,
        file_values,
        "DENDROFLOW_ENVIRONMENT",
        DEFAULT_TARGET_ENVIRONMENT,
    )
    return _validate_environment_label(value)


def get_database_target() -> DatabaseTarget:
    """Capture the environment label and PostgreSQL settings once."""
    process_values, file_values = _configured_values()
    environment = _validate_environment_label(
        _read_value(
            process_values,
            file_values,
            "DENDROFLOW_ENVIRONMENT",
            DEFAULT_TARGET_ENVIRONMENT,
        )
    )
    parameters = {
        "host": _read_value(process_values, file_values, "POSTGRES_HOST", "localhost"),
        "port": _read_value(process_values, file_values, "POSTGRES_PORT", "5432"),
        "user": _read_value(process_values, file_values, "POSTGRES_USER"),
        "password": _read_value(process_values, file_values, "POSTGRES_PASSWORD"),
    }
    return DatabaseTarget(environment=environment, connection_parameters=parameters)
