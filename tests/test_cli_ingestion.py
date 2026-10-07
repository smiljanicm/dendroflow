import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from dendroflow.cli.main import main
from dendroflow.ingestion.models import (
    IngestionCounts,
    IngestionError,
    IngestionFileResult,
    ValueConflictSample,
)
from dendroflow.ingestion.service import IngestionProgressEvent


def _result(
    file_id,
    outcome="completed",
    *,
    error=None,
    counts=None,
):
    return IngestionFileResult(
        file_id=file_id,
        filepath=f"/data/{file_id}.csv",
        outcome=outcome,
        ingestion_run_id=100 + file_id,
        file_version_id=200 + file_id,
        snapshot_hash="sha256:test",
        resumed=False,
        counts=counts,
        error=error,
    )


@pytest.fixture
def cli_target(monkeypatch):
    target = SimpleNamespace(environment="local")
    monkeypatch.setattr(
        "dendroflow.cli.ingestion.get_database_target",
        lambda: target,
    )
    monkeypatch.setattr(
        "dendroflow.cli.ingestion.use_database_target",
        lambda selected: nullcontext(),
    )
    monkeypatch.setattr(
        "dendroflow.cli.ingestion.get_source_file_ids",
        lambda: (1, 2, 3),
    )
    return target


def test_ingest_help_documents_selection_modes(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["ingest", "--help"])

    assert caught.value.code == 0
    output = capsys.readouterr().out
    assert "--file-id ID" in output
    assert "--all" in output
    assert "--max-attempts N" in output
    assert "--json" in output
    assert "--progress" in output
    assert "--keep-snapshot" in output


def test_ingest_passes_keep_snapshot_option(cli_target, monkeypatch, capsys):
    calls = []

    def fake_ingest(file_id, *, max_attempts, keep_snapshot):
        calls.append((file_id, keep_snapshot))
        return _result(file_id)

    monkeypatch.setattr(
        "dendroflow.cli.ingestion.ingest_file_with_report", fake_ingest,
    )
    assert main(["ingest", "--file-id", "1", "--json", "--keep-snapshot"]) == 0
    assert calls == [(1, True)]


@pytest.mark.parametrize(
    "argv",
    [
        ["ingest"],
        ["ingest", "--all", "--file-id", "1"],
        ["ingest", "--file-id", "0"],
        ["ingest", "--file-id", "-1"],
        ["ingest", "--file-id", "abc"],
        ["ingest", "--all", "--max-attempts", "0"],
    ],
)
def test_ingest_usage_errors(argv, capsys):
    with pytest.raises(SystemExit) as caught:
        main(argv)

    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage:" in captured.err


def test_ingest_deduplicates_and_sorts_ids_before_processing(
    cli_target,
    monkeypatch,
    capsys,
):
    called = []

    def fake_ingest(file_id, *, max_attempts, on_progress):
        called.append((file_id, max_attempts))
        on_progress(IngestionProgressEvent(
            file_id=file_id,
            phase="batch_completed",
            batch_number=1,
            source_rows_examined=2,
            observations_inserted=2,
        ))
        return _result(file_id)

    monkeypatch.setattr(
        "dendroflow.cli.ingestion.ingest_file_with_report",
        fake_ingest,
    )

    assert main([
        "ingest",
        "--file-id", "3",
        "--file-id", "1",
        "--file-id", "3",
        "--max-attempts", "5",
    ]) == 0

    assert called == [(1, 5), (3, 5)]
    output = capsys.readouterr()
    assert "Target environment: local" in output.out
    assert "File 1: completed" in output.out
    assert "File 3: completed" in output.out
    assert "selected=2, completed=2" in output.out
    assert "File 1: starting ingestion" in output.err
    assert "File 3: batch 1; rows examined=2" in output.err


def test_ingest_json_progress_keeps_stdout_machine_readable(
    cli_target,
    monkeypatch,
    capsys,
):
    def fake_ingest(file_id, *, max_attempts, on_progress):
        on_progress(IngestionProgressEvent(
            file_id=file_id,
            phase="source_loaded",
            filepath=f"/data/{file_id}.csv",
        ))
        on_progress(IngestionProgressEvent(file_id=file_id, phase="snapshot"))
        on_progress(IngestionProgressEvent(
            file_id=file_id,
            phase="batch_completed",
            batch_number=1,
            source_rows_examined=250,
            observations_inserted=250,
        ))
        return _result(file_id)

    monkeypatch.setattr(
        "dendroflow.cli.ingestion.ingest_file_with_report",
        fake_ingest,
    )

    assert main(["ingest", "--file-id", "1", "--json", "--progress"]) == 0
    output = capsys.readouterr()
    document = json.loads(output.out)
    assert document["files"][0]["file_id"] == 1
    assert "File 1: filepath: /data/1.csv" in output.err
    assert "batch 1; rows examined=250" in output.err


def test_ingest_rejects_unknown_ids_before_ingestion(
    cli_target,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        "dendroflow.cli.ingestion.ingest_file_with_report",
        lambda *args, **kwargs: pytest.fail("ingestion started before preflight"),
    )

    assert main(["ingest", "--file-id", "2", "--file-id", "99"]) == 2

    output = capsys.readouterr()
    assert output.out == ""
    assert "Unknown file ID(s): 99" in output.err


def test_ingest_all_with_no_registered_files_succeeds(
    cli_target,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        "dendroflow.cli.ingestion.get_source_file_ids",
        lambda: (),
    )
    monkeypatch.setattr(
        "dendroflow.cli.ingestion.ingest_file_with_report",
        lambda *args, **kwargs: pytest.fail("there are no registered files"),
    )

    assert main(["ingest", "--all"]) == 0
    assert "selected=0" in capsys.readouterr().out


def test_ingest_json_emits_one_document_and_uses_exit_precedence(
    cli_target,
    monkeypatch,
    capsys,
):
    results = {
        1: _result(
            1,
            "deferred",
            error=IngestionError("file_busy", "file is locked"),
        ),
        2: _result(
            2,
            "needs_configuration",
            error=IngestionError("needs_configuration", "no interfaces"),
        ),
        3: _result(3, "already_completed"),
        4: _result(4, "completed"),
    }
    monkeypatch.setattr(
        "dendroflow.cli.ingestion.get_source_file_ids",
        lambda: (1, 2, 3, 4),
    )
    monkeypatch.setattr(
        "dendroflow.cli.ingestion.ingest_file_with_report",
        lambda file_id, **kwargs: results[file_id],
    )

    assert main(["ingest", "--all", "--json"]) == 1

    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert captured.err == ""
    assert document["schema_version"] == 1
    assert document["target_environment"] == "local"
    assert document["summary"] == {
        "completed": 1,
        "already_completed": 1,
        "deferred": 1,
        "needs_configuration": 1,
        "failed": 0,
        "selected": 4,
    }
    assert [item["file_id"] for item in document["files"]] == [1, 2, 3, 4]
    assert document["files"][0]["error"]["category"] == "file_busy"


def test_ingest_text_sends_file_diagnostics_to_stderr(
    cli_target,
    monkeypatch,
    capsys,
):
    result = _result(
        1,
        "failed",
        error=IngestionError(
            "observation_conflict",
            "stored value differs",
            batch_number=2,
            source_line=17,
        ),
        counts=IngestionCounts(
            source_rows_examined=10,
            observations_inserted=4,
            observations_unchanged=3,
            repeated_identity_rows=1,
            deferred_trailing_bytes=0,
        ),
    )
    monkeypatch.setattr(
        "dendroflow.cli.ingestion.ingest_file_with_report",
        lambda file_id, **kwargs: result,
    )

    assert main(["ingest", "--file-id", "1"]) == 1

    captured = capsys.readouterr()
    assert "Rows examined: 10" in captured.out
    assert "inserted=4, unchanged=3, repeated=1" in captured.out
    assert "observation_conflict" in captured.err
    assert "batch 2, source line 17" in captured.err


def test_ingest_reports_kept_cross_file_value_conflict(
    cli_target, monkeypatch, capsys,
):
    sample = ValueConflictSample(
        location_id=4, variable_id=1,
        timestamp="2024-06-18T14:05:00+01:00",
        stored_value=6721.562, incoming_value=6721.563,
        stored_interface_id=9, incoming_interface_id=14,
        incoming_source_line=30533,
    )
    result = _result(
        3, counts=IngestionCounts(
            source_rows_examined=31000, observations_inserted=250,
            observations_unchanged=154749, repeated_identity_rows=0,
            deferred_trailing_bytes=0, value_conflicts=1,
            conflict_samples=(sample,),
        ),
    )
    monkeypatch.setattr(
        "dendroflow.cli.ingestion.ingest_file_with_report",
        lambda file_id, **kwargs: result,
    )

    assert main(["ingest", "--file-id", "3"]) == 0
    output = capsys.readouterr().out
    assert "value_conflicts=1" in output
    assert "6721.562" in output and "6721.563" in output
    assert "source line 30533" in output

    assert main(["ingest", "--file-id", "3", "--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    counts = document["files"][0]["counts"]
    assert counts["value_conflicts"] == 1
    assert counts["conflict_samples"][0]["incoming_source_line"] == 30533


def test_ingest_returns_deferred_exit_code_when_no_other_errors(
    cli_target,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        "dendroflow.cli.ingestion.ingest_file_with_report",
        lambda file_id, **kwargs: _result(
            file_id,
            "deferred",
            error=IngestionError("source_changing", "source is active"),
        ),
    )

    assert main(["ingest", "--file-id", "1"]) == 3
    assert "File 1: deferred" in capsys.readouterr().out


def test_ingest_reports_invalid_database_target_without_ingestion(
    monkeypatch,
    capsys,
):
    def invalid_target():
        raise RuntimeError("invalid environment label")

    monkeypatch.setattr(
        "dendroflow.cli.ingestion.get_database_target",
        invalid_target,
    )
    monkeypatch.setattr(
        "dendroflow.cli.ingestion.ingest_file_with_report",
        lambda *args, **kwargs: pytest.fail("ingestion started without a target"),
    )

    assert main(["ingest", "--all"]) == 2
    assert "Invalid database target" in capsys.readouterr().err


def test_ingest_returns_interrupted_exit_code(
    cli_target,
    monkeypatch,
    capsys,
):
    def interrupt(file_id, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "dendroflow.cli.ingestion.ingest_file_with_report",
        interrupt,
    )

    assert main(["ingest", "--file-id", "1"]) == 130
    assert "Ingestion interrupted" in capsys.readouterr().err
