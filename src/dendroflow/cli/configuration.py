import argparse
import sys

from pydantic import ValidationError

from dendroflow.configuration import (
    ConfigParseError,
    ConfigValidationError,
    load_config,
    validate_config,
)


def _format_location(location: tuple[str | int, ...]) -> str:
    path = ""
    for part in location:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else part
    return path or "<root>"


def validate(args: argparse.Namespace) -> int:
    """Validate configuration without resolving database resources."""
    try:
        config = load_config(args.path)
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
        print(f"Configuration valid: {args.path}")
        print("Database state was not checked.")
        return 0

    print(f"Configuration validation failed: {args.path}", file=sys.stderr)
    for issue in issues:
        print(f"  - {issue}", file=sys.stderr)
    return 2

