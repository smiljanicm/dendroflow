import argparse
import sys
from pathlib import Path

from dendroflow.database import DATABASES
from dendroflow.migrations import migrate_database

from .configuration import validate


def migrate(_args: argparse.Namespace) -> int:
    """Apply pending migrations to all DendroFlow databases."""
    for database in DATABASES:
        print(f"Migrating {database}...")

        try:
            applied_versions = migrate_database(database)
        except Exception as error:  # noqa: BLE001 -- report failures at the CLI boundary
            print(
                f"  Migration failed for {database}: {error}",
                file=sys.stderr,
            )
            return 1

        if applied_versions:
            for version in applied_versions:
                print(f"  Applied {version}")
        else:
            print("  No pending migrations")

    print("Migration complete.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; argparse exits for help and usage errors."""
    parser = argparse.ArgumentParser(
        prog="dendroflow",
        description="Manage DendroFlow databases and configuration.",
    )
    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )
    migration_parser = commands.add_parser(
        "migrate",
        help="Apply pending database migrations.",
        description="Apply pending migrations to all DendroFlow databases.",
    )
    migration_parser.set_defaults(handler=migrate)

    config_parser = commands.add_parser(
        "config",
        help="Validate and manage configuration.",
    )
    config_commands = config_parser.add_subparsers(
        dest="config_command",
        required=True,
    )
    validation_parser = config_commands.add_parser(
        "validate",
        help="Validate a YAML configuration without database access.",
    )
    validation_parser.add_argument(
        "path",
        type=Path,
        help="Path to the YAML configuration file.",
    )
    validation_parser.set_defaults(handler=validate)

    args = parser.parse_args(argv)
    return args.handler(args)
