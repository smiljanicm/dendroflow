import hashlib

import pytest

from dendroflow.ingestion.snapshots import (
    SourceFileChangingError,
    _wait_until_stable,
    capture_source_snapshot,
)


def test_capture_snapshot_is_content_addressed_and_defers_partial_line(tmp_path):
    source = tmp_path / "logger.csv"
    source.write_bytes(b"timestamp,value\n2026-01-01,1\n2026-01-02,2")

    snapshot = capture_source_snapshot(
        source,
        file_id=12,
        directory=tmp_path / "staging",
        settle_seconds=0,
    )

    complete_content = b"timestamp,value\n2026-01-01,1\n"
    assert snapshot.snapshot_path.read_bytes() == complete_content
    assert snapshot.captured_size == len(source.read_bytes())
    assert snapshot.deferred_bytes == len(b"2026-01-02,2")
    assert snapshot.fingerprint.file_size == len(complete_content)
    assert snapshot.fingerprint.file_hash == (
        "sha256:" + hashlib.sha256(complete_content).hexdigest()
    )

    repeated = capture_source_snapshot(
        source,
        file_id=12,
        directory=tmp_path / "staging",
        settle_seconds=0,
    )
    assert repeated.snapshot_path == snapshot.snapshot_path
    assert repeated.snapshot_path.read_bytes() == complete_content


def test_capture_snapshot_empty_without_complete_record(tmp_path):
    source = tmp_path / "logger.csv"
    source.write_bytes(b"partial record")

    snapshot = capture_source_snapshot(
        source,
        file_id=1,
        directory=tmp_path / "staging",
        settle_seconds=0,
    )

    assert snapshot.snapshot_path.read_bytes() == b""
    assert snapshot.fingerprint.file_size == 0
    assert snapshot.deferred_bytes == len(b"partial record")


def test_capture_snapshot_rejects_source_changed_during_capture(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "logger.csv"
    source.write_bytes(b"header\nrow\n")
    def change_after_stability_check(path, **kwargs):
        stable_stat = _wait_until_stable(path, **kwargs)
        path.write_bytes(b"header\nrow\nnew\n")
        return stable_stat

    monkeypatch.setattr(
        "dendroflow.ingestion.snapshots._wait_until_stable",
        change_after_stability_check,
    )

    with pytest.raises(SourceFileChangingError, match="changed while being captured"):
        capture_source_snapshot(
            source,
            file_id=1,
            directory=tmp_path / "staging",
            settle_seconds=0,
            max_attempts=1,
        )

    assert list((tmp_path / "staging" / "1").glob("*.snapshot")) == []
