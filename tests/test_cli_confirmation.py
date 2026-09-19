from dataclasses import replace

import psycopg
import pytest

from dendroflow.cli.confirmation import review_for_apply
from dendroflow.configuration.plan import (
    FieldChange,
    PlanAction,
    PlanError,
    PlanErrorCode,
    PlannedRef,
    PlanWarning,
    ResolvedPlan,
    ResolvedPlanItem,
    ResolvedSiteValues,
)


@pytest.fixture(autouse=True)
def block_database_and_unexpected_prompts(monkeypatch):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("Review must not connect to PostgreSQL")

    def unexpected_prompt(*args, **kwargs):
        pytest.fail("Unexpected confirmation prompt")

    monkeypatch.setattr(psycopg, "connect", unexpected_connection)
    monkeypatch.setattr("builtins.input", unexpected_prompt)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)


def create_item():
    return ResolvedPlanItem(
        "site:new",
        "site",
        PlanAction.CREATE,
        ResolvedSiteValues("station", "Station"),
    )


def identity_plan():
    return ResolvedPlan(
        metadata_items=(
            replace(
                create_item(),
                action=PlanAction.UPDATE,
                database_id=7,
                changes=(FieldChange("site_code", "old", "station", True),),
            ),
        ),
    )


@pytest.mark.parametrize("reuse", [False, True])
def test_no_write_plans_need_no_prompt(reuse, capsys):
    items = ()
    if reuse:
        items = (
            replace(create_item(), action=PlanAction.REUSE, database_id=7),
        )
    plan = ResolvedPlan(metadata_items=items)

    assert review_for_apply(plan) == 0
    captured = capsys.readouterr()
    assert "Configuration plan" in captured.out
    assert "No writes are required." in captured.out
    assert "Database outcome:" not in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("answer", ["y", "yes", " YES "])
def test_interactive_acceptance_follows_preview(answer, monkeypatch, capsys):
    plan = ResolvedPlan(metadata_items=(create_item(),))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    prompts = []

    def respond(prompt):
        prompts.append(prompt)
        preview = capsys.readouterr()
        assert "CREATE site 'site:new'" in preview.out
        assert preview.err == ""
        return answer

    monkeypatch.setattr("builtins.input", respond)

    assert review_for_apply(plan) == 0
    assert prompts == ["Apply this plan? [y/N] "]
    assert plan.metadata_items == (create_item(),)


@pytest.mark.parametrize("answer", ["", "n", "no", "maybe"])
def test_declined_or_unrecognized_answer_cancels(answer, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    plan = ResolvedPlan(metadata_items=(create_item(),))

    assert review_for_apply(plan) == 3
    assert "Apply cancelled. No changes were written." in capsys.readouterr().err


def test_eof_cancels_review(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def end_input(prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", end_input)

    assert review_for_apply(ResolvedPlan(metadata_items=(create_item(),))) == 3
    assert "Apply cancelled" in capsys.readouterr().err


def test_keyboard_interrupt_propagates(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def interrupt(prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)

    with pytest.raises(KeyboardInterrupt):
        review_for_apply(ResolvedPlan(metadata_items=(create_item(),)))


def test_noninteractive_writes_require_yes(capsys):
    plan = ResolvedPlan(metadata_items=(create_item(),))

    assert review_for_apply(plan) == 3
    captured = capsys.readouterr()
    assert "CREATE site 'site:new'" in captured.out
    assert "--yes is required for non-interactive apply" in captured.err


@pytest.mark.parametrize("interactive", [False, True])
def test_yes_skips_prompt_but_preserves_preview(interactive, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: interactive)
    plan = ResolvedPlan(metadata_items=(create_item(),))

    assert review_for_apply(plan, yes=True) == 0
    captured = capsys.readouterr()
    assert "CREATE site 'site:new'" in captured.out
    assert "Database outcome:" not in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("yes", [False, True])
def test_identity_flag_is_required_even_with_yes(yes, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    plan = identity_plan()

    assert review_for_apply(plan, yes=yes) == 3
    captured = capsys.readouterr()
    assert "Confirmation required: yes" in captured.out
    assert "--confirm-identity-changes is required" in captured.err
    assert plan.requires_confirmation


def test_identity_flag_does_not_replace_execution_confirmation(capsys):
    assert review_for_apply(identity_plan(), confirm_identity_changes=True) == 3
    assert "--yes is required" in capsys.readouterr().err


def test_both_flags_allow_identity_update_review(capsys):
    plan = identity_plan()

    assert review_for_apply(
        plan,
        yes=True,
        confirm_identity_changes=True,
    ) == 0
    captured = capsys.readouterr()
    assert "[identity change]" in captured.out
    assert captured.err == ""
    assert plan.requires_confirmation
    assert plan.metadata_items[0].database_id == 7


def test_identity_flag_with_interactive_confirmation(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    prompts = []

    def accept(prompt):
        prompts.append(prompt)
        return "yes"

    monkeypatch.setattr("builtins.input", accept)

    assert review_for_apply(identity_plan(), confirm_identity_changes=True) == 0
    assert prompts == ["Apply this plan? [y/N] "]
    assert capsys.readouterr().err == ""


def test_explicit_item_confirmation_is_enforced(capsys):
    item = replace(create_item(), confirmation_required=True)

    assert review_for_apply(ResolvedPlan(metadata_items=(item,)), yes=True) == 3
    assert "--confirm-identity-changes is required" in capsys.readouterr().err


@pytest.mark.parametrize("approve", [False, True])
def test_plan_errors_block_review_regardless_of_flags(approve, capsys):
    plan = replace(
        identity_plan(),
        errors=(
            PlanError(
                PlanErrorCode.CONFLICT,
                "site",
                "sites[0]",
                "Conflicting site definition",
            ),
        ),
    )

    assert review_for_apply(
        plan,
        yes=approve,
        confirm_identity_changes=approve,
    ) == 2
    captured = capsys.readouterr()
    assert "Conflicting site definition" in captured.out
    assert "Apply blocked: resolve the reported errors" in captured.err
    assert "--confirm-identity-changes is required" not in captured.err


@pytest.mark.parametrize("approve", [False, True])
def test_dependency_cycle_blocks_review_before_confirmation(approve, capsys):
    first = replace(
        create_item(),
        plan_id="site:a",
        values=ResolvedSiteValues("a", "A", parent=PlannedRef("site", "site:b")),
        confirmation_required=True,
    )
    second = replace(
        create_item(),
        plan_id="site:b",
        values=ResolvedSiteValues("b", "B", parent=PlannedRef("site", "site:a")),
    )
    plan = ResolvedPlan(metadata_items=(first, second))

    assert review_for_apply(
        plan,
        yes=approve,
        confirm_identity_changes=approve,
    ) == 2
    captured = capsys.readouterr()
    assert "Preparation failed [PLAN_NOT_APPLICABLE]" in captured.err
    assert "--confirm-identity-changes is required" not in captured.err


def test_warnings_are_visible_without_blocking_review(capsys):
    plan = ResolvedPlan(
        metadata_items=(create_item(),),
        warnings=(PlanWarning("example", "sites[0]", "Review this site"),),
    )

    assert review_for_apply(plan, yes=True) == 0
    captured = capsys.readouterr()
    assert "Review this site" in captured.out
    assert captured.err == ""

