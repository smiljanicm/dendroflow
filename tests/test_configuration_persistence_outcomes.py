import pytest

from dendroflow.configuration import persistence
from dendroflow.configuration.persistence.models import (
    ApplyError,
    ApplyErrorCode,
    ApplyExecutionError,
    ApplyItemResult,
    ApplyResult,
    ApplyStageStatus,
    ApplyStatus,
)
from dendroflow.configuration.plan import PlanAction


@pytest.mark.parametrize(
    ("status", "metadata", "raw"),
    [
        ("success", "not_required", "not_required"),
        ("success", "committed", "not_required"),
        ("success", "not_required", "committed"),
        ("success", "committed", "committed"),
        ("failed", "failed", "not_required"),
        ("failed", "failed", "not_started"),
        ("failed", "not_required", "failed"),
        ("partial", "committed", "failed"),
        ("partial", "committed", "not_started"),
        ("unknown", "unknown", "not_required"),
        ("unknown", "unknown", "not_started"),
        ("unknown", "not_required", "unknown"),
        ("unknown", "committed", "unknown"),
    ],
    ids=[
        "no-writes",
        "metadata-only-success",
        "raw-only-success",
        "both-stages-committed",
        "metadata-only-failure",
        "metadata-failure-blocks-raw",
        "raw-only-failure",
        "raw-failure-after-metadata-commit",
        "metadata-cleanup-failure-blocks-raw",
        "metadata-only-uncertain",
        "uncertain-metadata-blocks-raw",
        "raw-only-uncertain",
        "uncertain-raw-after-metadata-commit",
    ],
)
def test_valid_apply_outcomes(status, metadata, raw):
    result = ApplyResult(
        status=ApplyStatus(status),
        metadata_status=ApplyStageStatus(metadata),
        raw_status=ApplyStageStatus(raw),
    )

    assert result.status.value == status
    assert result.metadata_status.value == metadata
    assert result.raw_status.value == raw
    assert result.items == ()


@pytest.mark.parametrize(
    ("status", "metadata", "raw"),
    [
        ("success", "committed", "not_started"),
        ("success", "committed", "unknown"),
        ("failed", "not_required", "not_required"),
        ("failed", "failed", "failed"),
        ("failed", "failed", "committed"),
        ("failed", "unknown", "not_started"),
        ("partial", "not_required", "failed"),
        ("partial", "committed", "not_required"),
        ("partial", "committed", "unknown"),
        ("unknown", "committed", "failed"),
        ("unknown", "unknown", "committed"),
        ("unknown", "unknown", "unknown"),
    ],
    ids=[
        "success-with-unstarted-raw",
        "success-with-uncertain-raw",
        "failure-with-no-failed-stage",
        "raw-cannot-fail-after-metadata-failure",
        "raw-cannot-commit-after-metadata-failure",
        "uncertainty-is-not-known-failure",
        "partial-requires-committed-metadata",
        "partial-requires-unfinished-raw-work",
        "uncertain-raw-is-not-known-partial",
        "unknown-requires-uncertain-stage",
        "raw-cannot-commit-after-uncertain-metadata",
        "raw-cannot-start-after-uncertain-metadata",
    ],
)
def test_invalid_apply_outcomes_are_rejected(status, metadata, raw):
    with pytest.raises(ValueError, match="invalid apply outcome"):
        ApplyResult(
            status=ApplyStatus(status),
            metadata_status=ApplyStageStatus(metadata),
            raw_status=ApplyStageStatus(raw),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "success"),
        ("metadata_status", "not_required"),
        ("raw_status", "not_required"),
    ],
)
def test_outcome_fields_require_enum_members(field, value):
    arguments = {
        "status": ApplyStatus.SUCCESS,
        "metadata_status": ApplyStageStatus.NOT_REQUIRED,
        "raw_status": ApplyStageStatus.NOT_REQUIRED,
    }
    arguments[field] = value

    with pytest.raises(TypeError, match=field):
        ApplyResult(**arguments)


def test_execution_error_can_report_committed_success_after_cleanup_failure():
    result = ApplyResult(
        status=ApplyStatus.SUCCESS,
        metadata_status=ApplyStageStatus.COMMITTED,
        raw_status=ApplyStageStatus.COMMITTED,
    )

    error = ApplyExecutionError(
        "connection cleanup failed after commit",
        result=result,
    )

    assert isinstance(error, RuntimeError)
    assert error.result is result
    assert str(error) == "connection cleanup failed after commit"


@pytest.mark.parametrize(
    "cause",
    [
        RuntimeError("RAW connection failed"),
        ApplyError(
            ApplyErrorCode.UNRESOLVED_PLANNED_REF,
            "required deployment registration is unavailable",
        ),
    ],
    ids=["driver-error", "apply-error"],
)
def test_execution_error_preserves_outcome_items_and_original_cause(cause):
    committed_item = ApplyItemResult(
        plan_id="deployment",
        resource_type="deployment",
        action=PlanAction.CREATE,
        database_id=91,
    )
    result = ApplyResult(
        status=ApplyStatus.PARTIAL,
        metadata_status=ApplyStageStatus.COMMITTED,
        raw_status=ApplyStageStatus.FAILED,
        items=(committed_item,),
    )

    with pytest.raises(ApplyExecutionError) as caught:
        try:
            raise cause
        except Exception as original:
            raise ApplyExecutionError(
                "RAW stage failed after METADATA committed",
                result=result,
            ) from original

    assert caught.value.result is result
    assert caught.value.result.items == (committed_item,)
    assert caught.value.__cause__ is cause

    if isinstance(cause, ApplyError):
        assert cause.code == ApplyErrorCode.UNRESOLVED_PLANNED_REF


def test_public_api_exports_execution_error():
    assert persistence.ApplyExecutionError is ApplyExecutionError

