"""Shared environment and database handling for workbook CLI commands."""

import argparse
import sys
from collections.abc import Callable

from dendroflow.config import (
    DatabaseTarget,
    get_database_target,
    get_target_environment,
)
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
