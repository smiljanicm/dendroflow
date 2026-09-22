"""Read stored configuration into DataFrames for workbook export preparation."""

from types import MappingProxyType

import pandas as pd
from psycopg import sql

from dendroflow.database import connect

# Fixed, application-owned SQL identifiers. Column order is explicit, with each
# resource's primary key first. Relationships retain database IDs at this stage.
_METADATA_TABLES = (
    ("sites", "sites", (
        "site_id", "site_code", "name", "description",
        "latitude", "longitude", "parent_id",
    )),
    ("location_types", "location_types", (
        "location_type_id", "type", "description",
    )),
    ("sensor_types", "sensor_types", (
        "sensor_type_id", "type", "description",
    )),
    ("variables", "variables", (
        "variable_id", "variable", "derived", "description",
    )),
    ("sensor_models", "sensor_models", (
        "sensor_model_id", "manufacturer", "model", "sensor_type_id",
    )),
    ("sensors", "sensors", (
        "sensor_id", "serial_number", "sensor_model_id", "description",
    )),
    ("locations", "locations", (
        "location_id", "site_id", "location_type_id", "latitude", "longitude",
        "height_above_ground", "azimuth",
    )),
    ("location_labels", "location_labels", (
        "location_label_id", "location_id", "label", "valid_from", "valid_to",
    )),
    ("deployments", "deployments", (
        "deployment_id", "sensor_id", "location_id", "variable_id",
        "valid_from", "valid_to",
    )),
)

_RAW_TABLES = (
    ("files", "files", (
        "file_id", "filepath", "timestamp_timezone", "timestamp_format",
        "reader_config",
    )),
    ("interfaces", "sensor_file_interfaces", (
        "interface_id", "file_id", "deployment_id", "timestamp_column",
        "values_column", "unit",
    )),
)

_DATABASE_TABLES = (
    ("dendroflow_metadata", _METADATA_TABLES),
    ("dendroflow_raw", _RAW_TABLES),
)

# Shared with export preparation so its input contract follows the SQL reads.
SOURCE_COLUMNS = MappingProxyType({
    sheet: columns
    for _, tables in _DATABASE_TABLES
    for sheet, _, columns in tables
})


def read_configuration_frames() -> dict[str, pd.DataFrame]:
    """Read all METADATA/RAW configuration rows using fresh owned connections.

    Return one caller-owned DataFrame per resource sheet, including empty
    tables. Columns contain database values, not workbook aliases or roles.
    Rows are ordered by primary key. Object dtype prevents implicit conversion
    of nullable IDs into floating point and preserves psycopg's Python values.

    Each database is read in its own read-only, repeatable-read transaction.
    This is not an atomic snapshot across the two databases. Any connection,
    query, conversion, or transaction-exit error propagates; no partial mapping
    is returned. Connection contexts perform transaction cleanup and close.

    No observations, ingestion history, CLEAN data, or physical source files
    are read. These in-memory frames are export inputs, not a stored baseline.
    All configuration rows are loaded into memory; scoping is a later step.
    """
    frames: dict[str, pd.DataFrame] = {}
    for database, tables in _DATABASE_TABLES:
        with connect(database) as connection:
            # connect() supplies a fresh, non-autocommit psycopg connection.
            # Set both modes before the first data query establishes a snapshot.
            connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            for sheet_name, table_name, columns in tables:
                query = sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
                    sql.SQL(", ").join(map(sql.Identifier, columns)),
                    sql.Identifier(table_name),
                    sql.Identifier(columns[0]),
                )
                with connection.execute(query) as cursor:
                    rows = cursor.fetchall()
                frames[sheet_name] = pd.DataFrame(
                    rows, columns=columns, dtype=object,
                )

    return frames
