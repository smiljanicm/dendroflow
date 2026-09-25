import argparse
import sys
from pathlib import Path

from dendroflow.database import DATABASES
from dendroflow.migrations import migrate_database

from .configuration import apply, plan, validate
from .workbook import convert_workbook, export_workbook, validate_workbook_file


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


def workbook_help(args: argparse.Namespace) -> int:
    """Show workbook commands when only the command group was supplied."""
    args.workbook_parser.print_help()
    return 2


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

    planning_parser = config_commands.add_parser(
        "plan",
        help="Preview resolved operations without database writes.",
    )
    planning_parser.add_argument(
        "path",
        type=Path,
        help="Path to the YAML configuration file.",
    )
    planning_parser.set_defaults(handler=plan)

    apply_parser = config_commands.add_parser(
        "apply",
        help="Review and apply a YAML configuration.",
    )
    apply_parser.add_argument(
        "path",
        type=Path,
        help="Path to the YAML configuration file.",
    )
    apply_parser.add_argument(
        "--yes",
        action="store_true",
        help="Approve execution without an interactive prompt.",
    )
    apply_parser.add_argument(
        "--confirm-identity-changes",
        action="store_true",
        help="Explicitly authorize identity-changing updates.",
    )
    apply_parser.set_defaults(handler=apply)

    workbook_parser = config_commands.add_parser(
        "workbook",
        help="Export and process configuration workbooks.",
        description="Manage the Excel configuration workbook workflow.",
    )
    workbook_parser.set_defaults(
        handler=workbook_help,
        workbook_parser=workbook_parser,
    )
    workbook_commands = workbook_parser.add_subparsers(dest="workbook_command")
    export_parser = workbook_commands.add_parser(
        "export",
        help="Export current configuration to an XLSX workbook.",
    )
    export_parser.add_argument(
        "output",
        type=Path,
        help="Path for the new .xlsx workbook.",
    )
    selection = export_parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--all",
        action="store_true",
        help="Export all configuration resources.",
    )
    selection.add_argument(
        "--site-id",
        type=int,
        action="append",
        metavar="ID",
        help="Export a site and its configuration closure; may be repeated.",
    )
    export_parser.set_defaults(handler=export_workbook)

    workbook_validate_parser = workbook_commands.add_parser(
        "validate",
        help="Validate a workbook without database access.",
        description="Check workbook structure, values, identities, relationships, and declared scope.",
    )
    workbook_validate_parser.add_argument(
        "path",
        type=Path,
        help="Path to the .xlsx workbook.",
    )
    workbook_validate_parser.set_defaults(handler=validate_workbook_file)

    workbook_convert_parser = workbook_commands.add_parser(
        "convert",
        help="Compare a workbook with current databases and write CONFIG YAML.",
        description="Compare and convert a validated workbook to CONFIG YAML.",
    )
    workbook_convert_parser.add_argument(
        "workbook",
        type=Path,
        help="Path to the .xlsx workbook.",
    )
    workbook_convert_parser.add_argument(
        "output",
        type=Path,
        help="Path for a new .yaml or .yml configuration file.",
    )
    workbook_convert_parser.set_defaults(handler=convert_workbook)

    args = parser.parse_args(argv)
    return args.handler(args)
