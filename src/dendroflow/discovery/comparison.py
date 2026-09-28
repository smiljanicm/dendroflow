"""Compare scanned file paths with read-only RAW registrations."""

from dataclasses import dataclass
from pathlib import Path

from .models import DiscoveryFileResult, RegisteredFile
from .scanner import DiscoveryScan, ScanError, matches_filters


class DuplicateRegisteredPathError(ValueError):
    """Raised when distinct registrations resolve to the same filesystem path."""


@dataclass(frozen=True)
class DiscoveryComparison:
    """Filesystem scan results classified against RAW file registrations."""

    scan: DiscoveryScan
    files: tuple[DiscoveryFileResult, ...]

    @property
    def complete(self) -> bool:
        """Whether every scan root was inspected."""

        return self.scan.complete

    @property
    def scan_errors(self) -> tuple[ScanError, ...]:
        """Filesystem paths that could not be inspected."""

        return self.scan.errors


def _normalize_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    try:
        return candidate.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise ValueError(f"cannot normalize file path {path!s}: {error}") from error


def _scope_relative_path(path: Path, root: Path) -> str | None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    if not relative.parts:
        return None
    return relative.as_posix()


def _registration_index(
    registrations: tuple[RegisteredFile, ...],
) -> dict[Path, RegisteredFile]:
    by_path: dict[Path, RegisteredFile] = {}
    for registration in registrations:
        path = _normalize_path(registration.filepath)
        previous = by_path.get(path)
        if previous is not None and previous != registration:
            raise DuplicateRegisteredPathError(
                "registered file paths normalize to the same location: "
                f"file IDs {previous.file_id} and {registration.file_id} "
                f"both resolve to {path}"
            )
        by_path[path] = registration
    return by_path


def compare_discovery(
    scan: DiscoveryScan,
    registrations: tuple[RegisteredFile, ...],
    *,
    recursive: bool = False,
    includes: tuple[str, ...] = (),
    excludes: tuple[str, ...] = (),
) -> DiscoveryComparison:
    """Classify scanned paths and in-scope missing registrations.

    Missing results are emitted only when at least one complete root contains
    the registered path and its root-relative path passes the scan filters.
    A discovered path found under any selected root is never reported missing.
    """

    registrations_by_path = _registration_index(registrations)
    discovered_paths = {
        _normalize_path(path)
        for path in scan.files
    }
    results: list[DiscoveryFileResult] = []

    for path in sorted(discovered_paths, key=str):
        registration = registrations_by_path.get(path)
        if registration is None:
            result = DiscoveryFileResult(
                path=path,
                state="unregistered",
                file_id=None,
                interface_count=None,
            )
        else:
            state = (
                "registered"
                if registration.interface_count > 0
                else "needs_configuration"
            )
            result = DiscoveryFileResult(
                path=path,
                state=state,
                file_id=registration.file_id,
                interface_count=registration.interface_count,
            )
        results.append(result)

    discovered_set = set(discovered_paths)
    for path, registration in sorted(
        registrations_by_path.items(),
        key=lambda item: str(item[0]),
    ):
        if path in discovered_set:
            continue

        in_complete_scope = any(
            root.complete
            and (relative := _scope_relative_path(path, root.root)) is not None
            and (recursive or "/" not in relative)
            and matches_filters(
                relative,
                includes=includes,
                excludes=excludes,
            )
            for root in scan.roots
        )
        if in_complete_scope:
            results.append(
                DiscoveryFileResult(
                    path=path,
                    state="missing",
                    file_id=registration.file_id,
                    interface_count=registration.interface_count,
                )
            )

    results.sort(key=lambda item: (str(item.path), item.state, item.file_id or 0))
    return DiscoveryComparison(scan=scan, files=tuple(results))
