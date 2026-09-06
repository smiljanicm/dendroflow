from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd


@dataclass(frozen=True)
class TabularBatch:
    """A batch of tabular data with physical source-file provenance."""

    dataframe: pd.DataFrame
    source_line_numbers: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.dataframe) != len(self.source_line_numbers):
            raise ValueError(
                "DataFrame rows and source line numbers must have equal length"
            )


class TabularReader(Protocol):
    """Read tabular data as one or more provenance-aware batches."""

    def read(self, path: Path) -> Iterator[TabularBatch]:
        ...
