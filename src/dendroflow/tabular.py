from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

import pandas as pd

class TabularReader(Protocol):
"""Read tabular data as one or more DataFrame batches."""

def read(self, path: Path) -> Iterator[pd.DataFrame]:
    ...
