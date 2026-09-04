from pathlib import Path
import os
import re

from dendroflow.database import connect


MIGRATION_FILENAME_PATTERN = re.compile(r"^\d{3}_[a-z0-9_]+\.sql$")


def get_migrations_directory(database: str) -> Path:
    """Return the migrations directory for a DendroFlow database."""
    project_root = Path(
        os.getenv("DENDROFLOW_ROOT", Path.cwd())
    )

    return (
        project_root
        / "db"
        / database.removeprefix("dendroflow_")
        / "migrations"
    )

def validate_migration_filename(path: Path) -> None:
    """Validate a migration filename."""
    if not MIGRATION_FILENAME_PATTERN.fullmatch(path.name):
        raise RuntimeError(
            "Invalid migration filename: "
            f"{path.name}. Expected NNN_description.sql."
        )


def get_migration_files(database: str) -> list[Path]:
    """Return validated SQL migration files in version order."""
    migrations_directory = get_migrations_directory(database)

    if not migrations_directory.exists():
        raise RuntimeError(
            f"Migration directory does not exist: {migrations_directory}"
        )

    migration_files = sorted(
        migrations_directory.glob("*.sql"),
        key=lambda path: path.name,
    )

    for migration_file in migration_files:
        validate_migration_filename(migration_file)

    return migration_files


def ensure_migration_table(database: str) -> None:
    """Create the migration tracking table if it does not exist."""
    with connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def get_applied_migrations(database: str) -> set[str]:
    """Return the versions of migrations already applied."""
    with connect(database) as connection:
        rows = connection.execute(
            """
            SELECT version
            FROM schema_migrations
            """
        ).fetchall()

    return {row[0] for row in rows}

def apply_migration(database: str, migration_file: Path) -> None:
    """Apply one migration and record it as successfully applied."""
    version = migration_file.name

    sql = migration_file.read_text()

    with connect(database) as connection:
        connection.execute(sql)

        connection.execute(
            """
            INSERT INTO schema_migrations (version)
            VALUES (%s)
            """,
            (version,),
        )

def get_pending_migrations(database: str) -> list[Path]:
    """Return migration files that have not yet been applied."""
    migration_files = get_migration_files(database)
    applied_migrations = get_applied_migrations(database)

    return [
        migration_file
        for migration_file in migration_files
        if migration_file.name not in applied_migrations
    ]

def migrate_database(database: str) -> list[str]:
    """Apply all pending migrations for one database."""
    ensure_migration_table(database)

    pending_migrations = get_pending_migrations(database)

    applied_versions: list[str] = []

    for migration_file in pending_migrations:
        apply_migration(database, migration_file)
        applied_versions.append(migration_file.name)

    return applied_versions
