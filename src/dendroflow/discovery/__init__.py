"""Filesystem discovery primitives for registered DendroFlow sources."""

from .comparison import (
    DiscoveryComparison,
    DuplicateRegisteredPathError,
    compare_discovery,
)
from .models import DiscoveryFileResult, DiscoveryState, RegisteredFile
from .registrations import get_registered_files
from .scanner import (
    DiscoveredFile,
    DiscoveryScan,
    RootScan,
    ScanError,
    matches_filters,
    scan_directories,
)

__all__ = [
    "DiscoveredFile",
    "DiscoveryComparison",
    "DiscoveryFileResult",
    "DiscoveryScan",
    "DiscoveryState",
    "DuplicateRegisteredPathError",
    "RegisteredFile",
    "RootScan",
    "ScanError",
    "compare_discovery",
    "get_registered_files",
    "matches_filters",
    "scan_directories",
]
