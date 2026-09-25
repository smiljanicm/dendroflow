"""Shared environment and database handling for workbook CLI commands."""

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path

import psycopg

from dendroflow.config import (
    DatabaseTarget,
    get_database_target,
    get_target_environment,
)
from dendroflow.configuration.workbook.preparation import (
    WorkbookExportError,
    prepare_workbook_export,
)
from dendroflow.configuration.workbook.schema import RESOURCE_SHEETS
from dendroflow.configuration.workbook.source import read_configuration_frames
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
