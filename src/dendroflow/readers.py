from collections.abc import Iterator
from itertools import islice
from pathlib import Path
from typing import Any

import pandas as pd

from dendroflow.tabular import TabularBatch, TabularReader


class CsvReader:
    """Read CSV-compatible tabular files with physical line provenance."""

    def __init__(
        self,
        *,
        header: int | None = 0,
        skiprows: int | list[int] | None = None,
        chunksize: int | None = None,
        **kwargs: Any,
    ) -> None:
        self.header = header
        self.skiprows = skiprows
        self.chunksize = chunksize
        self.kwargs = kwargs

    def _iter_data_line_numbers(self, path: Path) -> Iterator[int]:
        """Yield 1-based physical line numbers for parsed data rows."""

        if self.skiprows is None:
            skipped_rows: set[int] = set()
            skip_first_rows = 0
        elif isinstance(self.skiprows, int):
            skipped_rows = set()
            skip_first_rows = self.skiprows
        else:
            skipped_rows = set(self.skiprows)
            skip_first_rows = 0

        skip_blank_lines = self.kwargs.get(
            "skip_blank_lines",
            True,
        )

        encoding = self.kwargs.get(
            "encoding",
            "utf-8",
        )

        first_data_candidate = (
            0
            if self.header is None
            else self.header + 1
        )

        candidate_index = 0

        with path.open(
            "r",
            encoding=encoding,
        ) as file:
            for zero_based_index, line in enumerate(file):
                if zero_based_index < skip_first_rows:
                    continue
                
                if zero_based_index in skipped_rows:
                    continue

                if skip_blank_lines and not line.strip():
                    continue

                if candidate_index >= first_data_candidate:
                    yield zero_based_index + 1

                candidate_index += 1

    def read(self, path: Path) -> Iterator[TabularBatch]:
        line_numbers = iter(self._iter_data_line_numbers(path))

        result = pd.read_csv(
            path,
            header=self.header,
            skiprows=self.skiprows,
            chunksize=self.chunksize,
            **self.kwargs,
        )

        if self.chunksize is None:
            dataframe = result

            source_lines = tuple(
                islice(line_numbers, len(dataframe))
            )

            yield TabularBatch(
                dataframe=dataframe,
                source_line_numbers=source_lines,
            )
            return

        for dataframe in result:
            source_lines = tuple(
                islice(line_numbers, len(dataframe))
            )

            yield TabularBatch(
                dataframe=dataframe,
                source_line_numbers=source_lines,
            )


def reader_from_config(config: dict[str, Any]) -> TabularReader:
    """Create a tabular reader from reader configuration."""

    reader_type = config.get("reader")
    options = config.get("options", {})

    if reader_type == "csv":
        return CsvReader(**options)

    raise ValueError(f"Unsupported reader type: {reader_type}")
