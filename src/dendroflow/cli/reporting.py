from collections.abc import Mapping
from dataclasses import fields
from datetime import datetime

from dendroflow.configuration.persistence.models import (
    ApplyError,
    ApplyErrorCode,
    ApplyExecutionError,
    ApplyItemResult,
    ApplyResult,
    ApplyStatus,
)
from dendroflow.configuration.persistence.transactions import StageTransactionError
from dendroflow.configuration.plan import (
    ExistingRef,
    PlanAction,
    PlannedRef,
    ResolvedPlan,
    ResolvedPlanItem,
)


def _format_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, ExistingRef):
        return f"existing {value.resource_type} #{value.database_id}"
    if isinstance(value, PlannedRef):
        return f"planned {value.resource_type} {value.plan_id!r}"
    if isinstance(value, Mapping):
        entries = sorted(
            (_format_value(key), _format_value(item))
            for key, item in value.items()
        )
        return "{" + ", ".join(
            f"{key}: {item}" for key, item in entries
        ) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_format_value(item) for item in value) + "]"
    return repr(value)


def _item_heading(item: ResolvedPlanItem | ApplyItemResult) -> str:
    heading = (
        f"{item.action.value.upper()} {item.resource_type} "
        f"{item.plan_id!r}"
    )
    if item.database_id is not None:
        heading += f" (database_id={item.database_id})"
    return heading


def _counts(items: tuple[ResolvedPlanItem, ...]) -> str:
    return ", ".join(
        f"{action.value.upper()}={sum(item.action == action for item in items)}"
        for action in PlanAction
    )


def format_plan(plan: ResolvedPlan) -> str:
    """Describe resolved intent; this does not establish apply readiness."""
    lines = [
        "Configuration plan",
        f"Total: {_counts(plan.items)}",
        f"Errors: {len(plan.errors)}; warnings: {len(plan.warnings)}",
        "Confirmation required: "
        + ("yes" if plan.requires_confirmation else "no"),
    ]

    for stage, items in (
        ("METADATA", plan.metadata_items),
        ("RAW", plan.raw_items),
    ):
        lines.extend(["", f"{stage}: {_counts(items)}"])
        if not items:
            lines.append("  (no items)")
        for item in items:
            lines.append(f"  {_item_heading(item)}")
            if item.source_path is not None:
                lines.append(f"    source: {item.source_path!r}")
            if item.requires_confirmation:
                lines.append("    confirmation required")
            if item.identity is not None:
                identity = ", ".join(
                    f"{name}={_format_value(value)}"
                    for name, value in item.identity.components
                )
                lines.append(f"    identity: {identity}")
            lines.append("    values:")
            for field in fields(item.values):
                value = _format_value(getattr(item.values, field.name))
                lines.append(f"      {field.name}: {value}")
            if item.changes:
                lines.append("    changes:")
                for change in item.changes:
                    marker = " [identity change]" if change.identity_change else ""
                    lines.append(
                        f"      {change.field}: "
                        f"{_format_value(change.before)} -> "
                        f"{_format_value(change.after)}{marker}"
                    )

    if plan.warnings:
        lines.extend(["", "Warnings:"])
        for warning in plan.warnings:
            lines.append(
                f"  {warning.code} at {warning.source_path!r}: "
                f"{warning.message}"
            )
    if plan.errors:
        lines.extend(["", "Errors:"])
        for error in plan.errors:
            lines.append(
                f"  {error.code.value.upper()} {error.resource_type} "
                f"at {error.source_path!r}: {error.message}"
            )
            if error.candidate_ids:
                candidates = ", ".join(str(item) for item in error.candidate_ids)
                lines.append(f"    candidate IDs: {candidates}")

    return "\n".join(lines)


def format_apply_result(result: ApplyResult) -> str:
    """Describe known database outcomes, including outcomes carried by errors."""
    lines = [
        f"Database outcome: {result.status.value.upper()}",
        f"METADATA: {result.metadata_status.value.upper()}",
        f"RAW: {result.raw_status.value.upper()}",
        "",
        "Reported items (committed writes and completed REUSE operations):",
    ]
    if result.items:
        lines.extend(f"  {_item_heading(item)}" for item in result.items)
    else:
        lines.append("  (none reported)")

    if result.status == ApplyStatus.PARTIAL:
        lines.extend([
            "",
            "METADATA committed; required RAW work did not complete.",
            "Inspect database state and review a new plan before retrying.",
        ])
    elif result.status == ApplyStatus.UNKNOWN:
        lines.extend([
            "",
            "A transaction outcome is uncertain.",
            "Missing item results do not prove rollback.",
            "Establish database state before another apply attempt.",
        ])
    return "\n".join(lines)


def _describe_error(error: BaseException) -> str:
    label = type(error).__name__
    if isinstance(error, ApplyError):
        label += f" [{error.code.value.upper()}]"
    return f"{label}: {error}"


def format_apply_error(error: ApplyExecutionError) -> str:
    """Explain an execution failure without changing its database outcome."""
    lines = [f"Apply did not finish cleanly: {error}"]
    cleanup_lines: list[str] = []
    cleanup_ids: set[int] = set()
    seen = {id(error)}
    cause = error.__cause__
    stale = False

    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, StageTransactionError):
            for label, secondary in (
                ("Rollback error", cause.rollback_error),
                ("Close error", cause.close_error),
            ):
                if secondary is not None:
                    cleanup_lines.append(f"{label}: {_describe_error(secondary)}")
                    cleanup_ids.add(id(secondary))
        elif id(cause) not in cleanup_ids:
            lines.append(f"Cause: {_describe_error(cause)}")

        if isinstance(cause, ApplyError) and cause.code == ApplyErrorCode.STALE_PLAN:
            stale = True
        cause = cause.__cause__

    lines.extend(cleanup_lines)

    if error.result.status == ApplyStatus.SUCCESS:
        lines.append(
            "Required database work completed; cleanup failed. "
            "Do not repeat committed operations because of this error."
        )
    elif error.result.status == ApplyStatus.FAILED:
        lines.append(
            "No write stage is reported as committed. "
            "Resolve the cause, then build and review a fresh plan."
        )

    if stale:
        lines.append(
            "The plan is stale. Resolve current database state and review "
            "a new plan before retrying."
        )

    lines.append("No automatic retry was attempted.")
    return "\n".join(lines)
