from pathlib import Path
import os


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
