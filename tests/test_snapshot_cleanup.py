from contextlib import contextmanager

import pytest

from dendroflow.ingestion import snapshots


@pytest.mark.parametrize("unfinished,should_exist", [(True, True), (False, False)])
def test_completed_snapshot_cleanup_respects_unfinished_runs(
    tmp_path, monkeypatch, unfinished, should_exist
):
    digest = "a" * 64
    directory = tmp_path / "7"
    directory.mkdir()
    path = directory / f"{digest}.snapshot"
    path.write_bytes(b"old source")
    monkeypatch.setattr(snapshots, "snapshot_directory", lambda: tmp_path)

    class Connection:
        def execute(self, query, parameters):
            assert parameters == (7, f"sha256:{digest}")
            return self

        def fetchone(self):
            return (unfinished,)

    @contextmanager
    def connect(database):
        assert database == "dendroflow_raw"
        yield Connection()

    monkeypatch.setattr(snapshots, "connect", connect)
    assert snapshots.cleanup_completed_snapshot(7, f"sha256:{digest}", path) is not unfinished
    assert path.exists() is should_exist


def test_cleanup_rejects_unexpected_path(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "snapshot_directory", lambda: tmp_path)
    with pytest.raises(ValueError, match="unexpected path"):
        snapshots.cleanup_completed_snapshot(7, "sha256:" + "a" * 64,
                                             tmp_path / "different.snapshot")
