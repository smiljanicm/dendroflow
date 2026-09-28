from pathlib import Path

import pytest

from dendroflow.discovery import (
    DuplicateRegisteredPathError,
    RegisteredFile,
    compare_discovery,
    get_registered_files,
    scan_directories,
)


def _write(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("data", encoding="utf-8")
    return path


def _states(comparison):
    return {
        result.path.name: (
            result.state,
            result.file_id,
            result.interface_count,
        )
        for result in comparison.files
    }


def test_comparison_classifies_registered_unconfigured_unregistered_and_missing(
    tmp_path,
):
    root = tmp_path / "sources"
    registered = _write(root / "registered.csv")
    unconfigured = _write(root / "unconfigured.csv")
    unregistered = _write(root / "new.csv")

    scan = scan_directories((root,))
    comparison = compare_discovery(
        scan,
        (
            RegisteredFile(1, str(registered), 2),
            RegisteredFile(2, str(unconfigured), 0),
            RegisteredFile(3, str(root / "missing.csv"), 1),
            RegisteredFile(4, str(tmp_path / "outside.csv"), 1),
        ),
    )

    assert comparison.complete
    assert comparison.scan_errors == ()
    assert _states(comparison) == {
        "missing.csv": ("missing", 3, 1),
        "new.csv": ("unregistered", None, None),
        "registered.csv": ("registered", 1, 2),
        "unconfigured.csv": ("needs_configuration", 2, 0),
    }
    assert unregistered.exists()


def test_comparison_resolves_relative_registration_from_working_directory(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "sources"
    registered = _write(root / "relative.csv")

    comparison = compare_discovery(
        scan_directories((root,)),
        (RegisteredFile(12, "sources/relative.csv", 1),),
    )

    result = comparison.files[0]
    assert result.path == registered.resolve()
    assert result.state == "registered"
    assert result.file_id == 12


def test_missing_checks_use_the_selected_roots_and_filters(tmp_path):
    root = tmp_path / "sources"
    root.mkdir()
    scan = scan_directories(
        (root,),
        recursive=True,
        includes=("**/*.csv",),
        excludes=("temporary/**",),
    )
    registrations = (
        RegisteredFile(1, str(root / "missing.csv"), 1),
        RegisteredFile(2, str(root / "temporary" / "old.csv"), 1),
        RegisteredFile(3, str(root.parent / "outside.csv"), 1),
        RegisteredFile(4, str(root / "notes.txt"), 1),
    )

    comparison = compare_discovery(
        scan,
        registrations,
        includes=("**/*.csv",),
        excludes=("temporary/**",),
    )

    assert _states(comparison) == {
        "missing.csv": ("missing", 1, 1),
    }


def test_nonrecursive_scan_does_not_mark_nested_registrations_missing(tmp_path):
    root = tmp_path / "sources"
    root.mkdir()
    nested_registration = RegisteredFile(
        1,
        str(root / "archive" / "nested.csv"),
        1,
    )
    scan = scan_directories((root,))

    comparison = compare_discovery(scan, (nested_registration,))

    assert comparison.files == ()


def test_recursive_scan_can_mark_nested_registration_missing(tmp_path):
    root = tmp_path / "sources"
    root.mkdir()
    nested_registration = RegisteredFile(
        1,
        str(root / "archive" / "nested.csv"),
        1,
    )
    scan = scan_directories((root,), recursive=True)

    comparison = compare_discovery(
        scan,
        (nested_registration,),
        recursive=True,
    )

    assert _states(comparison) == {
        "nested.csv": ("missing", 1, 1),
    }


def test_incomplete_root_does_not_create_missing_results(
    tmp_path,
    monkeypatch,
):
    from dendroflow.discovery import scanner

    root = tmp_path / "sources"
    blocked = root / "unreadable"
    _write(root / "new.csv")
    _write(blocked / "placeholder.csv")
    original_scandir = scanner.os.scandir

    def fail_for_blocked(path):
        if Path(path) == blocked:
            raise PermissionError("access denied")
        return original_scandir(path)

    monkeypatch.setattr(scanner.os, "scandir", fail_for_blocked)
    scan = scan_directories((root,), recursive=True)
    comparison = compare_discovery(
        scan,
        (
            RegisteredFile(1, str(root / "unreadable" / "missing.csv"), 1),
            RegisteredFile(2, str(root / "not-seen.csv"), 1),
        ),
    )

    assert not comparison.complete
    assert len(comparison.scan_errors) == 1
    assert _states(comparison) == {
        "new.csv": ("unregistered", None, None),
    }


def test_overlapping_roots_do_not_duplicate_file_results(tmp_path):
    root = tmp_path / "sources"
    file_path = _write(root / "nested" / "data.csv")
    scan = scan_directories((root, root / "nested"), recursive=True)

    comparison = compare_discovery(scan, (RegisteredFile(9, str(file_path), 1),))

    assert len(comparison.files) == 1
    assert comparison.files[0].state == "registered"


def test_distinct_registrations_with_same_normalized_path_are_rejected(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    absolute = tmp_path / "same.csv"

    with pytest.raises(DuplicateRegisteredPathError, match="normalize"):
        compare_discovery(
            scan_directories((tmp_path,)),
            (
                RegisteredFile(1, str(absolute), 1),
                RegisteredFile(2, "same.csv", 1),
            ),
        )


def test_get_registered_files_reads_interface_counts(monkeypatch):
    rows = ((10, "/data/a.csv", 2), (11, "/data/b.csv", 0))

    class FakeCursor:
        def fetchall(self):
            return rows

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return None

        def execute(self, query):
            assert "LEFT JOIN sensor_file_interfaces" in query
            assert "COUNT(sensor_file_interfaces.interface_id)" in query
            return FakeCursor()

    connection = FakeConnection()
    monkeypatch.setattr(
        "dendroflow.discovery.registrations.connect",
        lambda database: connection,
    )

    assert get_registered_files() == (
        RegisteredFile(10, "/data/a.csv", 2),
        RegisteredFile(11, "/data/b.csv", 0),
    )
