"""Read-only file discovery command-line interface."""

import argparse
import json
import sys

import psycopg

from dendroflow.config import get_database_target
from dendroflow.database import use_database_target
from dendroflow.discovery import (
    DiscoveryComparison,
    DiscoveryFileResult,
    DiscoveryScan,
    compare_discovery,
    get_registered_files,
    scan_directories,
)

ACTIONABLE_STATES = frozenset(
    {"unregistered", "needs_configuration", "missing"},
)


def _summary(comparison: DiscoveryComparison) -> dict[str, int]:
    summary = {
        "total": len(comparison.files),
        "unregistered": 0,
        "needs_configuration": 0,
        "registered": 0,
        "missing": 0,
    }
    for result in comparison.files:
        summary[result.state] += 1
    return summary


def _file_document(result: DiscoveryFileResult) -> dict[str, object]:
    return {
        "path": str(result.path),
        "state": result.state,
        "file_id": result.file_id,
        "interface_count": result.interface_count,
    }


def _report_document(
    comparison: DiscoveryComparison,
    environment: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "target_environment": environment,
        "complete": comparison.complete,
        "summary": _summary(comparison),
        "files": [_file_document(result) for result in comparison.files],
        "scan_errors": [
            {"path": str(error.path), "message": error.message}
            for error in comparison.scan_errors
        ],
    }


def _format_text(
    comparison: DiscoveryComparison,
    environment: str,
) -> str:
    lines = [
        f"Target environment: {environment}",
        f"Scan complete: {str(comparison.complete).lower()}",
    ]

    for root in comparison.scan.roots:
        lines.append(f"Root: {root.root}")
        lines.append(f"  Complete: {str(root.complete).lower()}")

    for result in comparison.files:
        lines.append(f"File: {result.path}")
        lines.append(f"  State: {result.state}")
        if result.file_id is not None:
            lines.append(f"  File ID: {result.file_id}")
        if result.interface_count is not None:
            lines.append(f"  Configured interfaces: {result.interface_count}")

    for error in comparison.scan_errors:
        lines.append(f"Scan error: {error.path}: {error.message}")

    summary = _summary(comparison)
    lines.append(
        "Discovery summary: "
        + ", ".join(f"{key}={value}" for key, value in summary.items())
    )
    return "\n".join(lines)


def _exit_code(comparison: DiscoveryComparison) -> int:
    if any(result.state in ACTIONABLE_STATES for result in comparison.files):
        return 1
    if not comparison.complete:
        return 3
    return 0


def discover(args: argparse.Namespace) -> int:
    """Scan selected roots and compare them with RAW file registrations."""
    try:
        target = get_database_target()
        scan: DiscoveryScan = scan_directories(
            tuple(args.root),
            recursive=args.recursive,
            includes=tuple(args.include),
            excludes=tuple(args.exclude),
        )
    except KeyboardInterrupt:
        print("Discovery interrupted.", file=sys.stderr)
        return 130
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Invalid discovery request or database target: {error}", file=sys.stderr)
        return 2

    try:
        with use_database_target(target):
            registrations = get_registered_files()
        comparison = compare_discovery(
            scan,
            registrations,
            recursive=args.recursive,
            includes=tuple(args.include),
            excludes=tuple(args.exclude),
        )
    except KeyboardInterrupt:
        print("Discovery interrupted.", file=sys.stderr)
        return 130
    except (OSError, RuntimeError, ValueError, psycopg.Error) as error:
        print(f"Discovery comparison failed: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(_report_document(comparison, target.environment), indent=2))
    else:
        print(_format_text(comparison, target.environment))

    return _exit_code(comparison)
