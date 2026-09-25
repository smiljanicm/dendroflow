from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

import psycopg

from dendroflow.config import DatabaseTarget, get_connection_parameters

DATABASES = (
    "dendroflow_metadata",
    "dendroflow_raw",
    "dendroflow_clean",
)

_ACTIVE_TARGET: ContextVar[DatabaseTarget | None] = ContextVar(
    "dendroflow_database_target",
    default=None,
)


@contextmanager
def use_database_target(target: DatabaseTarget) -> Iterator[None]:
    """Use one captured target for every connection in this context."""
    token: Token[DatabaseTarget | None] = _ACTIVE_TARGET.set(target)
    try:
        yield
    finally:
        _ACTIVE_TARGET.reset(token)


def connect(
    database: str,
    *,
    target: DatabaseTarget | None = None,
) -> psycopg.Connection:
    """Connect to one of the DendroFlow PostgreSQL databases."""
    if database not in DATABASES:
        raise ValueError(f"Unknown DendroFlow database: {database}")

    selected_target = target or _ACTIVE_TARGET.get()
    parameters = (
        get_connection_parameters()
        if selected_target is None
        else selected_target.connection_parameters
    )

    return psycopg.connect(
        dbname=database,
        **parameters,
    )
