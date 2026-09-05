from collections.abc import Iterator
from pathlib import Path

import pandas as pd

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
