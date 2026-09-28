"""Data models for comparing filesystem discovery with RAW registrations."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DiscoveryState = Literal[
    "unregistered",
    "needs_configuration",
    "registered",
    "missing",
]


@dataclass(frozen=True)
class RegisteredFile:
    """A RAW file registration and its configured interface count."""

    file_id: int
    filepath: str
    interface_count: int

    def __post_init__(self) -> None:
        if self.file_id < 1:
            raise ValueError("file_id must be greater than zero")
        if not self.filepath:
            raise ValueError("filepath must not be empty")
        if self.interface_count < 0:
            raise ValueError("interface_count must not be negative")


@dataclass(frozen=True)
class DiscoveryFileResult:
    """One discovered or missing file and its registration state."""

    path: Path
    state: DiscoveryState
    file_id: int | None
    interface_count: int | None
