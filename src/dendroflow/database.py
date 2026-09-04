import psycopg

from dendroflow.config import get_connection_parameters


DATABASES = (
    "dendroflow_metadata",
    "dendroflow_raw",
    "dendroflow_clean",
)


def connect(database: str) -> psycopg.Connection:
    """Connect to one of the DendroFlow PostgreSQL databases."""
    if database not in DATABASES:
        raise ValueError(f"Unknown DendroFlow database: {database}")

    parameters = get_connection_parameters()

    return psycopg.connect(
        dbname=database,
        **parameters,
    )

