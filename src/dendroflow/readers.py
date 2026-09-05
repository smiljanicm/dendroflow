from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from typing import Any

from dendroflow.tabular import TabularReader

class CsvReader:
    """Read CSV-compatible tabular files."""

    def __init__(
        self,
        *,
        header: int = 0,
        skiprows: int | None = None,
        chunksize: int | None = None,
        **kwargs,
    ) -> None:
        self.header = header
        self.skiprows = skiprows
        self.chunksize = chunksize
        self.kwargs = kwargs

    def read(self, path: Path) -> Iterator[pd.DataFrame]:
        result = pd.read_csv(
            path,
            header=self.header,
            skiprows=self.skiprows,
            chunksize=self.chunksize,
            **self.kwargs,
        )

        if self.chunksize is None:
            yield result
        else:
            yield from result

def reader_from_config(config: dict[str, Any]) -> TabularReader:
    """Create a tabular reader from reader configuration."""

    reader_type = config.get("reader")
    options = config.get("options", {})

    if reader_type == "csv":
        return CsvReader(**options)

    raise ValueError(f"Unsupported reader type: {reader_type}")
