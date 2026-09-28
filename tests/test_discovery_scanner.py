from pathlib import Path

import pytest

from dendroflow.discovery import matches_filters, scan_directories


def _write(path: Path, contents: str = "data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return path


def test_scan_is_non_recursive_by_default_and_includes_all_regular_files(
    tmp_path,
):
    root = tmp_path / "sources"
    _write(root / "b.csv")
    _write(root / ".hidden")
    _write(root / "nested" / "a.csv")

    result = scan_directories((root,))

    assert result.complete
    assert result.files == (
        (root / ".hidden").resolve(),
        (root / "b.csv").resolve(),
    )
    assert [item.relative_path for item in result.roots[0].files] == [
        ".hidden",
        "b.csv",
    ]


def test_scan_recursively_applies_includes_and_exclusions(tmp_path):
    root = tmp_path / "sources"
    _write(root / "root.csv")
    _write(root / "station_a" / "data.csv")
    _write(root / "station_a" / "notes.txt")
    _write(root / "temporary" / "old.csv")

    result = scan_directories(
        (root,),
        recursive=True,
        includes=("**/*.csv",),
        excludes=("temporary/**",),
    )

    assert result.complete
    assert result.files == (
        (root / "root.csv").resolve(),
        (root / "station_a" / "data.csv").resolve(),
    )
    assert [
        item.relative_path for item in result.roots[0].files
    ] == ["root.csv", "station_a/data.csv"]


def test_scan_deduplicates_repeated_roots_and_exposes_overlapping_files(
    tmp_path,
):
    root = tmp_path / "sources"
    nested = root / "station_a"
    _write(root / "root.csv")
    _write(nested / "data.csv")

    result = scan_directories(
        (root, nested, root),
        recursive=True,
    )

    assert len(result.roots) == 2
    assert result.complete
    assert result.files == (
        (root / "root.csv").resolve(),
        (nested / "data.csv").resolve(),
    )


def test_filters_use_case_sensitive_component_globs():
    assert matches_filters("station_a/data.csv", includes=("**/*.csv",))
    assert matches_filters("data.csv", includes=("**/*.csv",))
    assert not matches_filters("station_a/data.csv", includes=("*.csv",))
    assert not matches_filters("station_a/DATA.CSV", includes=("**/*.csv",))
    assert not matches_filters(
        "temporary/data.csv",
        includes=("**/*.csv",),
        excludes=("temporary/**",),
    )


@pytest.mark.parametrize(
    "pattern",
    ("", "/absolute/*.csv", "../outside.csv", "sub/../outside.csv", r"sub\file.csv"),
)
def test_filters_reject_absolute_or_escaping_patterns(pattern):
    with pytest.raises(ValueError):
        matches_filters("data.csv", includes=(pattern,))


@pytest.mark.parametrize(
    ("path_kind", "message"),
    (("missing", "does not exist"), ("file", "not a directory")),
)
def test_scan_reports_invalid_roots_without_raising(
    tmp_path,
    path_kind,
    message,
):
    root = tmp_path / "invalid"
    if path_kind == "file":
        root.write_text("not a directory", encoding="utf-8")

    result = scan_directories((root,))

    assert not result.complete
    assert result.files == ()
    assert message in result.errors[0].message


def test_scan_reports_directory_errors_and_keeps_other_results(
    tmp_path,
    monkeypatch,
):
    from dendroflow.discovery import scanner

    root = tmp_path / "sources"
    blocked = root / "blocked"
    _write(root / "visible.csv")
    _write(blocked / "hidden.csv")
    original_scandir = scanner.os.scandir

    def fail_for_blocked(path):
        if Path(path) == blocked:
            raise PermissionError("access denied")
        return original_scandir(path)

    monkeypatch.setattr(scanner.os, "scandir", fail_for_blocked)
    result = scan_directories((root,), recursive=True)

    assert not result.complete
    assert result.files == ((root / "visible.csv").resolve(),)
    assert len(result.errors) == 1
    assert result.errors[0].path == blocked
    assert "access denied" in result.errors[0].message


def test_scan_ignores_file_and_directory_symlinks_and_rejects_symlink_root(
    tmp_path,
):
    root = tmp_path / "sources"
    target = tmp_path / "target"
    _write(root / "visible.csv")
    _write(target / "outside.csv")
    (root / "linked_file.csv").symlink_to(target / "outside.csv")
    (root / "linked_directory").symlink_to(target, target_is_directory=True)
    root_link = tmp_path / "source-link"
    root_link.symlink_to(root, target_is_directory=True)

    result = scan_directories((root,), recursive=True)
    linked_root_result = scan_directories((root_link,), recursive=True)

    assert result.complete
    assert result.files == ((root / "visible.csv").resolve(),)
    assert not linked_root_result.complete
    assert "symbolic link" in linked_root_result.errors[0].message


def test_scan_marks_unreadable_root_incomplete(tmp_path, monkeypatch):
    from dendroflow.discovery import scanner

    root = tmp_path / "sources"
    root.mkdir()
    original_scandir = scanner.os.scandir

    def fail_for_root(path):
        if Path(path) == root:
            raise PermissionError("access denied")
        return original_scandir(path)

    monkeypatch.setattr(scanner.os, "scandir", fail_for_root)
    result = scan_directories((root,))

    assert not result.complete
    assert result.files == ()
    assert result.errors[0].path == root
    assert "access denied" in result.errors[0].message


def test_scan_requires_at_least_one_root():
    with pytest.raises(ValueError, match="at least one"):
        scan_directories(())
