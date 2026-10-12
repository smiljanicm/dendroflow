"""Read-only file discovery command-line interface."""

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

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

WORKBOOK_FILE_COLUMNS = (
    "file_id", "ref", "row_role", "path", "timestamp_timezone",
    "timestamp_format", "reader_type", "reader_options",
)


def _write_workbook_csv(path: Path, comparison: DiscoveryComparison) -> int:
    """Write only unregistered paths as new workbook file rows."""
    new_files = sorted(
        (item for item in comparison.files if item.state == "unregistered"),
        key=lambda item: str(item.path),
    )
    created = False
    try:
        with path.open("x", newline="", encoding="utf-8") as output:
            created = True
            writer = csv.writer(output)
            writer.writerow(WORKBOOK_FILE_COLUMNS)
            for item in new_files:
                source_path = str(item.path)
                ref = "new_file_" + hashlib.sha256(
                    source_path.encode("utf-8")
                ).hexdigest()[:16]
                writer.writerow(("", ref, "edit", source_path, "", "", "csv", ""))
    except Exception:
        # Do not leave a partial CSV after a write failure. An existing file
        # must remain untouched when exclusive creation failed.
        if created:
            path.unlink(missing_ok=True)
        raise
    return len(new_files)


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

    csv_error_code = None
    if args.workbook_csv is not None:
        if not comparison.complete:
            print(
                "Workbook CSV was not written: discovery scan is incomplete.",
                file=sys.stderr,
            )
            csv_error_code = 3
        else:
            try:
                count = _write_workbook_csv(args.workbook_csv, comparison)
            except (OSError, ValueError) as error:
                print(f"Unable to write workbook CSV: {error}", file=sys.stderr)
                csv_error_code = 2
            else:
                print(
                    f"Wrote {count} new file row(s) to {args.workbook_csv}",
                    file=sys.stderr,
                )

    if args.json:
        print(json.dumps(_report_document(comparison, target.environment), indent=2))
    else:
        print(_format_text(comparison, target.environment))

    return csv_error_code if csv_error_code is not None else _exit_code(comparison)
