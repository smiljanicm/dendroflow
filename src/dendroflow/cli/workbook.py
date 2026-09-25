"""Shared environment and database handling for workbook CLI commands."""

import argparse
import os
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import psycopg

from dendroflow.config import (
    DatabaseTarget,
    get_database_target,
    get_target_environment,
)
from dendroflow.configuration.workbook.comparison import WorkbookComparisonError
from dendroflow.configuration.workbook.configuration import (
    WorkbookConfigurationError,
    generate_configuration,
)
from dendroflow.configuration.workbook.matching import (
    WorkbookMatchError,
    read_workbook_matches,
)
from dendroflow.configuration.workbook.parsing import (
    WorkbookParseError,
    parse_workbook,
)
from dendroflow.configuration.workbook.preparation import (
    WorkbookExportError,
    prepare_workbook_export,
)
from dendroflow.configuration.workbook.reader import (
    WorkbookReadError,
    read_workbook,
)
from dendroflow.configuration.workbook.schema import RESOURCE_SHEETS
from dendroflow.configuration.workbook.serialization import WorkbookSerializationError
from dendroflow.configuration.workbook.source import read_configuration_frames
from dendroflow.configuration.workbook.validation import (
    WorkbookValidationError,
    validate_workbook,
)
from dendroflow.configuration.workbook.verification import (
    WorkbookPlanVerificationError,
    verify_generated_configuration,
)
from dendroflow.configuration.workbook.writer import write_workbook_export
from dendroflow.database import use_database_target


def require_workbook_environment() -> str | None:
    """Read the workbook target label without requiring database credentials."""
    try:
        return get_target_environment()
    except RuntimeError as error:
        print(f"Workbook configuration error: {error}", file=sys.stderr)
        return None


def run_with_database_target(
    args: argparse.Namespace,
    operation: Callable[[argparse.Namespace, DatabaseTarget], int],
) -> int:
    """Run a database-backed workbook action using one captured target."""
    try:
        target = get_database_target()
    except RuntimeError as error:
        print(f"Workbook configuration error: {error}", file=sys.stderr)
        return 2

    with use_database_target(target):
        return operation(args, target)


def _output_path_error(path: Path) -> str | None:
    if path.suffix.lower() != ".xlsx":
        return "workbook output path must end with .xlsx"
    if not path.parent.exists() or not path.parent.is_dir():
        return f"output directory does not exist: {path.parent}"
    if os.path.lexists(path):
        return f"output file already exists: {path}"
    return None


def _export(args: argparse.Namespace, target: DatabaseTarget) -> int:
    try:
        frames = read_configuration_frames()
        site_ids = None if args.all else args.site_id
        prepared = prepare_workbook_export(frames, site_ids=site_ids)
        write_workbook_export(
            args.output,
            prepared,
            target_environment=target.environment,
        )
    except FileExistsError as error:
        print(f"Workbook export failed: {error}", file=sys.stderr)
        return 2
    except (WorkbookExportError, TypeError, ValueError) as error:
        print(f"Workbook export failed: {error}", file=sys.stderr)
        return 2
    except (OSError, psycopg.Error, RuntimeError) as error:
        print(f"Workbook export failed: {error}", file=sys.stderr)
        return 1

    print(f"Workbook exported: {args.output}")
    print(f"Target environment: {target.environment}")
    print(f"Scope: {prepared.scope}")
    if prepared.scope == "sites":
        print(f"Selected site IDs: {', '.join(map(str, prepared.site_ids))}")
    print("Rows: " + ", ".join(
        f"{spec.name}={len(prepared.frames[spec.name])}"
        for spec in RESOURCE_SHEETS
    ))
    return 0


def export_workbook(args: argparse.Namespace) -> int:
    """Export current configuration to a new populated XLSX workbook."""
    problem = _output_path_error(args.output)
    if problem is not None:
        print(f"Workbook export failed: {problem}", file=sys.stderr)
        return 2
    return run_with_database_target(args, _export)


def _report_workbook_issues(prefix: str, error: ValueError) -> int:
    issues = getattr(error, "issues", ())
    if issues:
        print(f"{prefix}:", file=sys.stderr)
        for issue in issues:
            location = issue.sheet or "workbook"
            if issue.coordinate:
                location += f"!{issue.coordinate}"
            print(f"  {location}: {issue.message}", file=sys.stderr)
    else:
        print(f"{prefix}: {error}", file=sys.stderr)
    return 2


def validate_workbook_file(args: argparse.Namespace) -> int:
    """Validate workbook structure and relationships without database IO."""
    environment = require_workbook_environment()
    if environment is None:
        return 2

    try:
        document = read_workbook(args.path, expected_environment=environment)
        parsed = parse_workbook(document)
        validate_workbook(parsed)
    except (WorkbookReadError, WorkbookParseError, WorkbookValidationError) as error:
        return _report_workbook_issues("Workbook validation failed", error)
    except (OSError, TypeError, ValueError) as error:
        print(f"Workbook validation failed: {error}", file=sys.stderr)
        return 2

    print(f"Workbook valid: {args.path}")
    print(f"Target environment: {parsed.metadata.target_environment}")
    print(f"Scope: {parsed.metadata.scope}")
    if parsed.metadata.scope == "sites":
        print(f"Selected site IDs: {', '.join(map(str, parsed.metadata.site_ids))}")
    print("Rows: " + ", ".join(
        f"{spec.name}={len(parsed.frames[spec.name])}"
        for spec in RESOURCE_SHEETS
    ))
    print("Checks: workbook structure, cell values, identities, relationships, and scope")
    return 0


def _yaml_output_path_error(path: Path) -> str | None:
    if path.suffix.lower() not in {".yaml", ".yml"}:
        return "configuration output path must end with .yaml or .yml"
    if not path.parent.exists() or not path.parent.is_dir():
        return f"output directory does not exist: {path.parent}"
    if os.path.lexists(path):
        return f"output file already exists: {path}"
    return None


def _convert(args: argparse.Namespace, target: DatabaseTarget) -> int:
    try:
        document = read_workbook(args.workbook, expected_environment=target.environment)
        parsed = parse_workbook(document)
        matched = read_workbook_matches(parsed)
        generated = generate_configuration(matched)
        verified = verify_generated_configuration(generated)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(verified.serialized.yaml_text)
    except (
        WorkbookReadError,
        WorkbookParseError,
        WorkbookValidationError,
        WorkbookMatchError,
        WorkbookComparisonError,
        WorkbookConfigurationError,
        WorkbookSerializationError,
    ) as error:
        return _report_workbook_issues("Workbook conversion failed", error)
    except WorkbookPlanVerificationError as error:
        print("Workbook plan verification failed:", file=sys.stderr)
        for issue in error.issues:
            print(f"  {issue}", file=sys.stderr)
        return 2
    except FileExistsError as error:
        print(f"Workbook conversion failed: {error}", file=sys.stderr)
        return 2
    except (OSError, TypeError, ValueError) as error:
        print(f"Workbook conversion failed: {error}", file=sys.stderr)
        return 2
    except (psycopg.Error, RuntimeError) as error:
        print(f"Workbook conversion failed: {error}", file=sys.stderr)
        return 1

    totals = Counter(
        row.status.value
        for rows in generated.comparison.rows.values()
        for row in rows
    )
    print(f"Configuration YAML written: {args.output}")
    print(f"Target environment: {target.environment}")
    print(f"Scope: {generated.comparison.metadata.scope}")
    print("Rows: " + ", ".join(
        f"{status}={totals.get(status, 0)}"
        for status in ("unchanged", "new", "update", "blocked")
    ))
    print(
        "Generated CONFIG plan verified against workbook intent; "
        "no database changes were applied."
    )
    print("Review the YAML, then use `dendroflow config plan` before applying it.")
    return 0


def convert_workbook(args: argparse.Namespace) -> int:
    """Convert a workbook to YAML after comparing with current databases."""
    problem = _yaml_output_path_error(args.output)
    if problem is not None:
        print(f"Workbook conversion failed: {problem}", file=sys.stderr)
        return 2
    return run_with_database_target(args, _convert)
