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
from dendroflow.configuration.persistence import apply_plan
from dendroflow.configuration.persistence.combined_preparation import prepare_plan
from dendroflow.configuration.persistence.models import (
    ApplyError,
    ApplyErrorCode,
    ApplyExecutionError,
    ApplyStatus,
)
from dendroflow.configuration.resolution.orchestration import resolve_config

from .confirmation import review_for_apply
from .reporting import format_apply_result, format_plan


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


def apply(args: argparse.Namespace) -> int:
    """Apply the exact resolved plan shown during review."""
    config = _load_validated_config(args.path)
    if config is None:
        return 2

    try:
        resolved = resolve_config(config)
    except (psycopg.Error, RuntimeError) as error:
        print(f"Configuration planning failed: {error}", file=sys.stderr)
        return 1

    review_code = review_for_apply(
        resolved,
        yes=args.yes,
        confirm_identity_changes=args.confirm_identity_changes,
    )
    if review_code != 0:
        return review_code

    try:
        result = apply_plan(
            resolved,
            confirm_identity_changes=args.confirm_identity_changes,
        )
    except ApplyExecutionError as error:
        print(format_apply_result(error.result))
        print(f"Apply did not finish cleanly: {error}", file=sys.stderr)
        return {
            ApplyStatus.PARTIAL: 4,
            ApplyStatus.UNKNOWN: 5,
        }.get(error.result.status, 1)
    except ApplyError as error:
        print(f"Apply blocked [{error.code.value.upper()}]: {error}", file=sys.stderr)
        return 3 if error.code == ApplyErrorCode.CONFIRMATION_REQUIRED else 2

    print(format_apply_result(result))
    return 0