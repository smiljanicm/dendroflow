"""Read-only directory scanning for source-file discovery."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path, PureWindowsPath


@dataclass(frozen=True)
class DiscoveredFile:
    """One regular file found under a scan root."""

    path: Path
    relative_path: str


@dataclass(frozen=True)
class ScanError:
    """A filesystem path that could not be inspected."""

    path: Path
    message: str


@dataclass(frozen=True)
class RootScan:
    """Files and errors collected while scanning one root."""

    root: Path
    files: tuple[DiscoveredFile, ...]
    errors: tuple[ScanError, ...]

    @property
    def complete(self) -> bool:
        """Whether every directory and entry in this root was inspected."""

        return not self.errors


@dataclass(frozen=True)
class DiscoveryScan:
    """Results from scanning one or more roots."""

    roots: tuple[RootScan, ...]

    @property
    def complete(self) -> bool:
        """Whether every selected root was scanned completely."""

        return all(root.complete for root in self.roots)

    @property
    def files(self) -> tuple[Path, ...]:
        """Return unique normalized paths in stable order."""

        paths = {
            discovered.path
            for root in self.roots
            for discovered in root.files
        }
        return tuple(sorted(paths, key=str))

    @property
    def errors(self) -> tuple[ScanError, ...]:
        """Return filesystem errors in root and path order."""

        errors = (
            error
            for root in self.roots
            for error in root.errors
        )
        return tuple(sorted(errors, key=lambda error: (str(error.path), error.message)))


def _validate_patterns(patterns: tuple[str, ...]) -> None:
    for pattern in patterns:
        if (
            not pattern
            or pattern.startswith("/")
            or PureWindowsPath(pattern).drive
            or PureWindowsPath(pattern).is_absolute()
            or "\\" in pattern
        ):
            raise ValueError(
                "glob patterns must be non-empty relative paths using '/'"
            )
        if ".." in pattern.split("/"):
            raise ValueError("glob patterns must not contain '..' components")


def _glob_matches(relative_path: str, pattern: str) -> bool:
    """Match slash-separated path components with recursive '**' support."""

    path_parts = relative_path.split("/")
    pattern_parts = pattern.split("/")

    @cache
    def match(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)

        component = pattern_parts[pattern_index]
        if component == "**":
            if pattern_index == len(pattern_parts) - 1:
                return True
            return any(
                match(next_path_index, pattern_index + 1)
                for next_path_index in range(path_index, len(path_parts) + 1)
            )

        return (
            path_index < len(path_parts)
            and fnmatch.fnmatchcase(path_parts[path_index], component)
            and match(path_index + 1, pattern_index + 1)
        )

    return match(0, 0)


def matches_filters(
    relative_path: str,
    *,
    includes: tuple[str, ...] = (),
    excludes: tuple[str, ...] = (),
) -> bool:
    """Return whether a root-relative POSIX path passes the scan filters.

    Multiple include patterns are combined with OR. Exclusions take
    precedence. Empty includes means all paths are included.
    """

    _validate_patterns(includes)
    _validate_patterns(excludes)

    return _matches_validated_filters(relative_path, includes, excludes)


def _matches_validated_filters(
    relative_path: str,
    includes: tuple[str, ...],
    excludes: tuple[str, ...],
) -> bool:
    included = not includes or any(
        _glob_matches(relative_path, pattern)
        for pattern in includes
    )
    excluded = any(
        _glob_matches(relative_path, pattern)
        for pattern in excludes
    )
    return included and not excluded


def _absolute_path(path: str | os.PathLike[str]) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return Path(os.path.abspath(candidate))


def scan_directories(
    roots: tuple[str | os.PathLike[str], ...],
    *,
    recursive: bool = False,
    includes: tuple[str, ...] = (),
    excludes: tuple[str, ...] = (),
) -> DiscoveryScan:
    """Scan directories without reading or modifying file contents.

    Roots are normalized, deduplicated, and scanned in stable order. Symlinks
    found inside a root are ignored. Files are returned per root so callers
    can make scope-aware decisions when a root is only partly readable.
    """

    if not roots:
        raise ValueError("at least one scan root is required")
    _validate_patterns(includes)
    _validate_patterns(excludes)

    absolute_roots = sorted({_absolute_path(root) for root in roots}, key=str)
    scans = tuple(
        _scan_root(
            root,
            recursive=recursive,
            includes=includes,
            excludes=excludes,
        )
        for root in absolute_roots
    )
    return DiscoveryScan(roots=scans)


def _scan_root(
    root: Path,
    *,
    recursive: bool,
    includes: tuple[str, ...],
    excludes: tuple[str, ...],
) -> RootScan:
    files: list[DiscoveredFile] = []
    errors: list[ScanError] = []

    if root.is_symlink():
        errors.append(ScanError(root, "scan root is a symbolic link"))
        return RootScan(root, (), tuple(errors))

    try:
        normalized_root = root.resolve(strict=False)
        if not normalized_root.exists():
            errors.append(ScanError(normalized_root, "scan root does not exist"))
            return RootScan(normalized_root, (), tuple(errors))
        if not normalized_root.is_dir():
            errors.append(ScanError(normalized_root, "scan root is not a directory"))
            return RootScan(normalized_root, (), tuple(errors))
    except (OSError, RuntimeError) as error:
        errors.append(ScanError(root, str(error)))
        return RootScan(root, (), tuple(errors))

    def visit(directory: Path, relative_parts: tuple[str, ...]) -> None:
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as error:
            errors.append(ScanError(directory, str(error)))
            return

        for entry in entries:
            entry_path = Path(entry.path)
            try:
                if entry.is_symlink():
                    continue
                relative_components = (*relative_parts, entry.name)
                relative_path = "/".join(relative_components)

                if entry.is_file(follow_symlinks=False):
                    if _matches_validated_filters(
                        relative_path,
                        includes,
                        excludes,
                    ):
                        files.append(
                            DiscoveredFile(
                                path=entry_path,
                                relative_path=relative_path,
                            )
                        )
                elif recursive and entry.is_dir(follow_symlinks=False):
                    visit(entry_path, relative_components)
            except OSError as error:
                errors.append(ScanError(entry_path, str(error)))

    visit(normalized_root, ())
    return RootScan(
        root=normalized_root,
        files=tuple(sorted(files, key=lambda item: item.relative_path)),
        errors=tuple(sorted(errors, key=lambda item: (str(item.path), item.message))),
    )
