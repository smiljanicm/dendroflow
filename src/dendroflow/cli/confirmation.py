import sys

from dendroflow.configuration.persistence.combined_preparation import prepare_plan
from dendroflow.configuration.persistence.models import ApplyError, ApplyErrorCode
from dendroflow.configuration.persistence.preflight import validate_plan_for_apply
from dendroflow.configuration.plan import ResolvedPlan

from .reporting import format_plan


def review_for_apply(
    plan: ResolvedPlan,
    *,
    yes: bool = False,
    confirm_identity_changes: bool = False,
) -> int:
    """Preview and authorize a resolved plan without executing it.

    Return 0 when the caller may proceed with this same plan,
    2 for invalid plans, or 3 for missing or declined confirmation.
    A successful review does not mean any database changes committed.
    """
    print(format_plan(plan), flush=True)

    if plan.errors:
        print(
            "Apply blocked: resolve the reported errors before applying.",
            file=sys.stderr,
        )
        return 2

    try:
        # Inspect dependencies before requesting execution authorization.
        prepared = prepare_plan(plan, confirm_identity_changes=True)
    except ApplyError as error:
        print(
            f"Preparation failed [{error.code.value.upper()}]: {error}",
            file=sys.stderr,
        )
        return 2

    try:
        # The inspection above does not satisfy the actual confirmation gate.
        validate_plan_for_apply(
            plan,
            confirm_identity_changes=confirm_identity_changes,
        )
    except ApplyError as error:
        if error.code == ApplyErrorCode.CONFIRMATION_REQUIRED:
            print(
                "Apply blocked: --confirm-identity-changes is required. "
                "No changes were written.",
                file=sys.stderr,
            )
            return 3
        print(f"Apply blocked [{error.code.value.upper()}]: {error}", file=sys.stderr)
        return 2

    if not prepared.requires_writes:
        print("No writes are required.")
        return 0

    if yes:
        return 0

    if not sys.stdin.isatty():
        print(
            "Apply blocked: --yes is required for non-interactive apply. "
            "No changes were written.",
            file=sys.stderr,
        )
        return 3

    try:
        answer = input("Apply this plan? [y/N] ")
    except EOFError:
        answer = ""

    if answer.strip().lower() not in {"y", "yes"}:
        print("Apply cancelled. No changes were written.", file=sys.stderr)
        return 3

    return 0
