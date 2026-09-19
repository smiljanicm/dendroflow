import argparse
import sys
from pathlib import Path

import psycopg
from pydantic import ValidationError

from dendroflow.configuration import (
    ConfigModel,
    ConfigParseError,
    ConfigValidationError,
    load_config,
    validate_config,
)
from dendroflow.configuration.persistence.combined_preparation import prepare_plan
from dendroflow.configuration.persistence.models import ApplyError
from dendroflow.configuration.resolution.orchestration import resolve_config

from .reporting import format_plan


def _format_location(location: tuple[str | int, ...]) -> str:
    path = ""
    for part in location:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else part
    return path or "<root>"


def _load_validated_config(path: Path) -> ConfigModel | None:
    """Load input and report validation errors shared by CONFIG commands."""
    try:
        config = load_config(path)
        validate_config(config)
    except ConfigParseError as error:
        issues = [str(error)]
    except UnicodeDecodeError:
        issues = ["configuration file must be UTF-8"]
    except ValidationError as error:
        issues = [
            f"{_format_location(issue['loc'])}: {issue['msg']}"
            for issue in error.errors(
                include_url=False,
                include_input=False,
            )
        ]
    except ConfigValidationError as error:
        issues = [
            f"{issue.path}: {issue.message}"
            for issue in error.issues
        ]
    else:
        return config

    print(f"Configuration validation failed: {path}", file=sys.stderr)
    for issue in issues:
        print(f"  - {issue}", file=sys.stderr)
    return None


def validate(args: argparse.Namespace) -> int:
    """Validate configuration without resolving database resources."""
    if _load_validated_config(args.path) is None:
        return 2

    print(f"Configuration valid: {args.path}")
    print("Database state was not checked.")
    return 0


def plan(args: argparse.Namespace) -> int:
    """Resolve and inspect a plan without applying operations."""
    config = _load_validated_config(args.path)
    if config is None:
        return 2

    try:
        resolved = resolve_config(config)
    except (psycopg.Error, RuntimeError) as error:
        print(f"Configuration planning failed: {error}", file=sys.stderr)
        return 1

    print(format_plan(resolved))

    if resolved.errors:
        print(
            "Planning blocked: resolve the reported errors before applying.",
            file=sys.stderr,
        )
        return 2

    try:
        # Inspection only: this does not authorize a subsequent apply.
        # Keep confirmation requirements on the original plan and report.
        prepare_plan(resolved, confirm_identity_changes=True)
    except ApplyError as error:
        print(
            f"Preparation failed [{error.code.value.upper()}]: {error}",
            file=sys.stderr,
        )
        return 2

    print()
    print("Preparation checks passed. No changes were written.")
    if resolved.requires_confirmation:
        print("Confirmation is still required before applying this plan.")
    print("This preview does not reserve database state.")
    return 0
