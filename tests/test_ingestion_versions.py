from pathlib import Path

import hashlib

from dendroflow.ingestion import (
    FileFingerprint,
    FileVersion,
    fingerprint_file,
    get_or_create_file_version,
)

def test_fingerprint_file(tmp_path):
    content = b"DendroFlow\nexample\n"

    path = tmp_path / "example.dat"
    path.write_bytes(content)

    fingerprint = fingerprint_file(path)

    expected_hash = hashlib.sha256(content).hexdigest()

    assert fingerprint.file_size == len(content)
    assert fingerprint.file_hash == f"sha256:{expected_hash}"

def test_get_or_create_file_version_reuses_existing_version(monkeypatch):
    fingerprint = FileFingerprint(
        file_hash="sha256:abc123",
        file_size=100,
    )

    class InsertResult:
        def fetchone(self):
            return None

    class SelectResult:
        def fetchone(self):
            return (
                7,
                1,
                "sha256:abc123",
                100,
            )

    class FakeConnection:
        def __init__(self):
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def execute(self, query, parameters):
            self.calls += 1

            if self.calls == 1:
                assert parameters == (
                    1,
                    "sha256:abc123",
                    100,
                )
                return InsertResult()

            assert parameters == (
                1,
                "sha256:abc123",
            )
            return SelectResult()

    monkeypatch.setattr(
        "dendroflow.ingestion.versions.connect",
        lambda database: FakeConnection(),
    )

    version = get_or_create_file_version(
        1,
        fingerprint,
    )

    assert version == FileVersion(
        file_version_id=7,
        file_id=1,
        file_hash="sha256:abc123",
        file_size=100,
    )

def test_get_or_create_file_version_creates_new_version(monkeypatch):
    fingerprint = FileFingerprint(
        file_hash="sha256:newhash",
        file_size=200,
    )

    class InsertResult:
        def fetchone(self):
            return (
                8,
                1,
                "sha256:newhash",
                200,
            )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def execute(self, query, parameters):
            assert parameters == (
                1,
                "sha256:newhash",
                200,
            )
            return InsertResult()

    monkeypatch.setattr(
        "dendroflow.ingestion.versions.connect",
        lambda database: FakeConnection(),
    )

    version = get_or_create_file_version(
        1,
        fingerprint,
    )

    assert version.file_version_id == 8
    assert version.file_hash == "sha256:newhash"
