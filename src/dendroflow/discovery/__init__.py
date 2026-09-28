"""Filesystem discovery primitives for registered DendroFlow sources."""

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
    "DiscoveryScan",
    "RootScan",
    "ScanError",
    "matches_filters",
    "scan_directories",
]
