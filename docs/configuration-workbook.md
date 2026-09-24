# CONFIG control workbook contract

## Status

G1 defines workbook format version 1, its sheet/column schema, and header checks.
G2.a adds an empty XLSX template writer using openpyxl. G2.b reads stored
configuration into pandas DataFrames. G2.c selects the export scope and prepares
workbook values and references. G2.d saves populated XLSX workbooks with export
metadata. G3.a reads workbook structure, validates metadata and retains raw cell
locations/types. G3.b parses resource cells into typed DataFrames with located
diagnostics. G3.c checks workbook identities, relationships, declared scope and
initial-label consistency without database access. G4.a matches current database
identities and scope. G4.b compares fields and reports new, unchanged, update,
and blocked rows. G4.c builds public lookups from current identities and checks
their uniqueness in the full source snapshot. G4.d assembles a validated CONFIG
model. YAML output/live verification and workbook CLI commands follow in G4.e-G5.
The rules below are requirements for those implementations, not claims that
header validation already enforces them.

The workflow is: fresh database export, Excel editing, comparison against the
current database, generated YAML, reviewed CONFIG plan, confirmed apply.
Each editing session starts with a fresh export. There is no baseline file,
automatic deletion, hash watcher, or automatic application.

## Sheets and headers

Exports contain `guide`, `workbook_info`, and all eleven resource sheets below.
Resource sheets use row 1 for headers and row 2 onwards for records. Empty
resource sheets retain every header. All listed headers are required, even for
nullable values. Sheet and column order can change; exact names cannot.
Unknown sheets, unknown/missing columns, and duplicate headers are errors.
The guide is optional on import, contains free text, and is not configuration.
Do not place explanatory or subtotal rows inside the resource tables.

Every resource sheet starts with its ID column, `ref`, and `row_role`, followed
by these data columns. The exporter uses the order below; the importer uses names.

| Sheet | ID column | Data columns |
| --- | --- | --- |
| sites | site_id | site_code, name, description, latitude, longitude, parent |
| location_types | location_type_id | type, description |
| sensor_types | sensor_type_id | type, description |
| variables | variable_id | variable, derived, description |
| sensor_models | sensor_model_id | manufacturer, model, sensor_type |
| sensors | sensor_id | serial_number, sensor_model, description |
| locations | location_id | site, location_type, latitude, longitude, height_above_ground, azimuth |
| location_labels | location_label_id | location, label, valid_from, valid_to, is_initial |
| deployments | deployment_id | sensor, location, variable, valid_from, valid_to |
| files | file_id | path, timestamp_timezone, timestamp_format, reader_type, reader_options |
| interfaces | interface_id | file, deployment, timestamp_column, values_column, unit |

The machine-readable schema is in
`src/dendroflow/configuration/workbook/schema.py`. It describes cell kinds,
nullability, relationship target sheets, and supported YAML update fields.
It is independent of pandas and the eventual XLSX library.

## Workbook information

`workbook_info` has `key` and `value` columns, with exactly one row for each key:

| Key | Meaning |
| --- | --- |
| format_version | Integer 1; reject unsupported versions |
| workbook_id | UUID identifying this export/template |
| target_environment | Explicit, non-secret identifier for the configured METADATA/RAW database pair |
| exported_at | Export time as an ISO 8601 UTC string; blank for an empty template |
| scope | `all`, `sites`, or `template` |
| site_ids | JSON array of selected site IDs as decimal strings; empty for `all` or `template` |

Do not store passwords or connection strings in a workbook. The environment
identifier must match the configured import target before IDs are interpreted.
It is provenance, not an authentication or permission mechanism. G2 Python
writers require the caller to supply this label; they do not verify it against
connection settings. G5 must bind the label to the configured database pair and
use it consistently for export and import. It must not be inferred solely from
database names, which can be identical on different servers.

## Export scope and shared resources

- `all`: include every configuration resource in METADATA and RAW, including
  unreferenced resources. Do not export observations, ingestion runs, file
  versions, or CLEAN data.
- `sites`: select exact site IDs, their locations, label histories, deployments,
  and interfaces for those deployments, together with the referenced files.
  Include the sensors, models, types, variables, and ancestor sites needed to
  resolve every relationship. Descendant sites are not selected implicitly.
- `template`: the same sheets and headers with no resource rows, used to create
  a setup in the chosen target environment.

Site-scoped exports include selected sites, their locations, labels, deployments,
and interfaces as `edit` rows. Ancestor sites, instrument/catalogue resources,
and files are `reference` rows. They can be shared outside the selected scope.
Other interfaces in a shared file are not implicitly selected.
Users export `all` to request supported changes to shared resources.
Rows added by users have `row_role=edit` and blank database IDs.

An `edit` role permits comparison for supported changes; it does not make every
field updatable. A `reference` row supplies a relationship target and requests
no mutation. Differences on reference rows must be reported and block conversion
until refreshed/reviewed, rather than silently accepted or applied.
Import must validate roles against the selected scope and current database
relationships; changing a cell from `reference` to `edit` is not authorization.
New relationships in a site-scoped workbook must remain within its selected
sites or supply supporting new resources. New sites require `all` or `template`.

## Identity and relationships

Database IDs are positive integers exported as decimal text to avoid Excel
rounding large IDs. Retain them unchanged. A blank ID indicates a row to resolve
as a possible new resource, not an instruction to INSERT unconditionally.
An existing ID that no longer exists is an error, not a request to recreate it.
Duplicate IDs within a resource sheet are errors.

Every row has a nonblank `ref`, unique within its sheet. Exported references can
use names such as `site_12` or `sensor_41`. Users supply references for new rows.
Relationship cells contain the target sheet's `ref`, never a row number or a
display label. The target sheet is fixed by the column schema. For example,
`sensors.sensor_model` refers to `sensor_models.ref`.
References are case-sensitive after trimming surrounding whitespace. Renaming
an alias requires updating its relationship cells but does not rename a database
record. Reference changes alone must not cause writes.

Match by resource ID and references, not row position. Sort normalized data for
deterministic reporting only. Missing rows never request deletion. Removing a
row still used by another row creates an unresolved-reference error.

## Location labels

Store each label once in `location_labels`. `is_initial` is a workbook helper,
not a database field. For existing locations the exporter marks the earliest
label according to the current location lookup order (`valid_from`, then ID).
That marker and existing label values cannot be edited in version 1.

A new location requires exactly one associated new label with `is_initial=TRUE`.
The YAML translator nests this row as the location's `initial_label`; it must
not also emit it in top-level `location_labels`. Additional new labels use
`is_initial=FALSE` and become top-level label declarations. Existing label rows
serve as context and for comparison; they are not redeclared as new initial
labels. Existing overlap and validity checks remain authoritative.

## Values and blank cells

The workbook describes desired field values, not a sparse update form.

- A blank nullable field means null. On an editable existing record, clearing
  such a field proposes a change to null. It never means "leave unchanged".
- A blank required field is an error. Boolean fields require TRUE or FALSE,
  including `variables.derived` and `location_labels.is_initial` on new rows.
- Nullable fields are descriptions, site parent, coordinate pairs, location
  height/azimuth, and validity end times. Database IDs are blank only for new rows.
- Keep identifiers, serial numbers and text as text, preserving leading zeros.
  Do not convert text such as `NA` or `NULL` into missing data automatically.
- Empty strings and whitespace-only text normalize to blank. Trim surrounding
  whitespace consistently with CONFIG models. Null and empty text are therefore
  not separately expressible in this format; diagnose unsupported legacy states
  rather than silently altering them during export/import.
- Numbers must be finite. Zero and FALSE are values, not blanks. Coordinate
  pairs and range constraints follow the existing CONFIG models. G2.d writes
  coordinates, height and azimuth as decimal text, preserving stored numeric
  precision through Excel's 15-significant-digit numeric limit. Keep text
  formatting and use a dot decimal separator; scientific notation is valid.
  These remain logical NUMBER fields in the schema and Python numbers in the
  prepared frames. G3 must parse the text back to finite numbers before
  comparison. Boolean cells remain native Excel booleans.
- Validity timestamps are ISO 8601 text with an explicit offset, for example
  `2026-01-01T00:00:00Z`. Export UTC; compare instants after normalization.
  Reject naive Excel date cells instead of guessing a timezone. The RAW
  `timestamp_timezone` field describes source measurements independently.
- `reader_options` is a JSON object, including `{}` for no options. Compare
  parsed objects, so object-key order does not cause differences. Array order
  remains meaningful. `reader_type` is currently `csv`.
- Formula cells and Excel error cells are not configuration input. Reject them
  with sheet/row/column diagnostics. Export literal strings as text, even when
  they begin with characters Excel might interpret as formulas.
- Ignore completely blank resource rows; reject partially populated invalid
  rows. Preserve original Excel row numbers for diagnostics before sorting.

G3 will implement these cell and relationship checks. G1 validates headers only.

## Supported changes and YAML boundary

The schema's `update_field` maps a workbook column to the existing public YAML
update model. Only those fields can generate UPDATE requests. In particular:

- Site `parent` can be supplied for a new site, but the public YAML update model
  currently does not expose parent changes, despite lower-level writer support.
- Existing location labels support no UPDATE operations.
- Existing files and interfaces support no RAW UPDATE operations.
- IDs, aliases, roles, and helper fields are not ordinary database update fields.

Differences in unsupported persisted fields block conversion and are reported;
they must not silently disappear or be converted into a replacement CREATE.
New rows still use normal CONFIG validation and compatible-resource resolution.
Unchanged records require no writes. Deletions and broadening UPDATE support
remain outside Phase G.

Workbook IDs are not currently valid YAML lookup fields. G4 must use verified
current selectors for those IDs, retain existing-resource reference bindings,
and prove that each generated lookup resolves the intended record. If the public
lookup contract cannot express a record unambiguously, stop with a diagnostic.
Any required selector extension must be a separately reviewed change, rather
than bypassing CONFIG resolution or persistence. Renames must select existing
records using their current identity, then express the new value in `set`.

Generated YAML is not a saved executable plan. A later plan/apply resolves it
against current database state again; it does not retain the workbook's original
database snapshot. Review that resulting plan. Stale-update guards apply to
supported UPDATE fields after planning, not to the entire editing session.
Without a baseline, independent database edits made during Excel editing can
appear as changes back to workbook values. Explicit review remains required.

## Acceptance and remaining implementation

G2 is implemented through Python APIs: template generation, database reading,
scope/value preparation, and populated writing with export metadata. Desktop
editing and the complete import/compare round trip still need acceptance checks.
G3.a reads structure and metadata; G3.b parses resource cells; G3.c validates
identities, relationships and roles within the workbook. Verification against
current database state belongs to G4.
G4 compares against databases and writes YAML; G5 adds CLI commands; G6 verifies
the complete round trip. Unsupported legacy database values need clear export
or conversion diagnostics, not silent normalization that changes their meaning.

The central acceptance case uses CONFIG-compatible records:
export, import unchanged, plan, and apply with zero database writes.
Additional cases cover reordered sheets/rows/columns, explicit nulls, new related
rows, stable IDs across supported renames, shared resources, unsupported edits,
wrong environments, invalid values, missing targets, and concurrent changes.

Run the G1 contract tests with:

```bash
pytest -q tests/test_configuration_workbook_schema.py
```

## Empty template generation (G2.a)

Install the updated package dependencies:

```bash
python -m pip install -e ".[dev]"
```

The Python entry point writes a new workbook without database access:

```python
from dendroflow.configuration.workbook.writer import write_workbook_template

path = write_workbook_template(
    "control-template.xlsx",
    target_environment="local-dev",
)
```

The explicit environment label identifies the intended database pair. G2.a does
not look it up or verify a connection; automatic environment configuration is
still pending. Labels must contain 1-128 characters after trimming and no
embedded control characters. Do not supply credentials or connection strings.

The result contains the guide, workbook information, and all resource headers.
It has a new workbook UUID, `scope=template`, an empty `site_ids` array, and no
export timestamp or resource records. Text columns have Excel text formatting,
headers remain visible while scrolling, and role/boolean/reader-type dropdowns
help users enter values. Dropdowns do not replace future Python validation.
Changing formatting or pasting cells can override Excel's text formatting;
check leading zeros and use value-only paste when entering identifiers.
Logical NUMBER columns also use text formatting to preserve numeric precision.

The output must use an `.xlsx` extension and an existing parent directory.
Existing files are never overwritten. Serialization finishes in memory before
opening the output file; an error during serialization creates no output.
Filesystem write failures can still leave an incomplete new file.

This step does not implement Excel import or database change planning. Inspect
the generated workbook in Excel or LibreOffice; do not expect edits to be
applied yet. Use the populated export API below for existing configurations.

```bash
pytest -q tests/test_configuration_workbook_writer.py
```

Tests reopen saved XLSX files to check structure, metadata, formatting, dropdown
ranges, literal text handling, and file-creation error behaviour. Desktop Excel
interaction and workbook layout should also be checked locally.

## Configuration database reading (G2.b)

```python
from dendroflow.configuration.workbook.source import read_configuration_frames

frames = read_configuration_frames()
for sheet_name, frame in frames.items():
    print(sheet_name, len(frame))
```

This requires the normal DendroFlow connection settings and migrated METADATA
and RAW databases. It returns eleven caller-owned pandas DataFrames, keyed by
the resource sheet names from G1. Every frame is present even if its table is
empty, with explicit columns and rows ordered by primary key.

These frames contain database columns and values, not the final Excel layout:

- Relationships retain integer IDs such as `site_id` and `sensor_model_id`.
- File rows retain `filepath` and the complete `reader_config` JSON object.
- `interfaces` reads the `sensor_file_interfaces` table.
- No `ref`, `row_role`, or `is_initial` values have been assigned yet.
- All columns use object dtype to preserve large IDs, Python nulls, booleans,
  timezone-aware timestamps, and JSON values without automatic type inference.
- Legacy values that cannot be expressed in the workbook contract are retained
  for later diagnostics. Missing label histories or cross-database deployment
  references are not silently removed by joins.

One fresh connection is opened for METADATA, then another for RAW. Before data
queries, each starts a read-only, repeatable-read transaction. Its table queries
therefore share one database snapshot. Connection contexts finish the transaction
and close the connection before returning data. Query, conversion, connection,
or transaction-exit errors propagate; no partial dictionary is returned.

There is no atomic snapshot across METADATA and RAW. Another process can change
relationships between those reads. Export preparation must detect missing
referenced records and report them, but cannot detect every concurrent change.
An export does not reserve database state for a later apply.

Only configuration tables are queried. Observations, file versions, ingestion
history, CLEAN tables, and physical source files are not read. All configuration
rows are loaded into memory at this stage; site filtering and reference closure
belong to the G2.c export-preparation step. The returned frames are transient
export inputs, not stored synchronization baselines.

```bash
pytest -q tests/test_configuration_workbook_source.py

DENDROFLOW_INTEGRATION=1 pytest -q \
  tests/integration/test_configuration_workbook_database.py
```

Unit tests exercise query routing, value preservation and failure propagation.
The opt-in PostgreSQL test runs the real SELECTs, checks the active read-only and
repeatable-read settings, and verifies the returned frame structure. It creates
or deletes no fixture records. It does not simulate concurrent writers or prove
cross-database snapshot consistency.

## Export preparation (G2.c)

```python
from dendroflow.configuration.workbook.preparation import prepare_workbook_export
from dendroflow.configuration.workbook.source import read_configuration_frames

source_frames = read_configuration_frames()

all_records = prepare_workbook_export(source_frames)
selected_sites = prepare_workbook_export(source_frames, site_ids=[2, 3])

print(selected_sites.scope)      # sites
print(selected_sites.site_ids)   # (2, 3)
print(selected_sites.frames["sites"])
```

Replace example IDs with actual IDs in your database. `site_ids=None` selects
all configuration records, including unreferenced resources. An explicit
selection must be nonempty and contain positive integer BIGINT IDs. Repeated
IDs are deduplicated, sorted and checked against the source sites. Descendant
sites are not selected implicitly.

Preparation performs no database or filesystem IO and leaves input frames
unchanged. The returned `WorkbookExport` has `scope`, `site_ids`, and fresh
caller-owned `frames`. Its frame keys, columns and column order match G1.
Frames include headers even when empty. Their rows are ordered numerically by
database ID; reordered input rows, columns or dictionary entries give the same
output. Output frames are mutable and are not stored baselines.

For site-scoped exports, selected sites, locations, full label histories,
deployments and matching interfaces are `edit` rows. Required ancestor sites,
location types, sensors, models, sensor types, variables and files are included
as `reference` rows. A selected ancestor stays editable. A shared file does not
pull in interfaces belonging to other sites. In an `all` export every included
row has role `edit`, subject to the existing per-field update restrictions.

The preparation step:

- Checks the eleven source frames, exact source columns and unique positive
  primary IDs before selecting records.
- Follows selected records' references to include their required targets, and
  rejects missing targets and cycles in site ancestry.
- Writes database IDs as decimal strings and deterministic aliases such as
  `site_2`, `sensor_model_40` and `deployment_80`. Relationship cells use those
  aliases rather than raw database IDs.
- Marks one earliest label per location, ordered by UTC instant then label ID.
  A selected location without label history is an error.
- Converts aware timestamps to ISO 8601 UTC text while preserving microseconds.
  Nullable values remain None; zero, FALSE and leading-zero text remain values.
- Splits RAW `reader_config` into `reader_type` and JSON `reader_options`.
  JSON object keys are sorted; array order remains intact. Only the currently
  supported csv reader and exactly the `reader`/`options` keys are accepted.

Selected cells must be representable without silent changes. Required nulls,
empty or padded text, non-finite numbers, invalid booleans, naive timestamps,
unsupported reader settings, non-JSON values, illegal XLSX characters and text
longer than 32767 characters are errors. The source reader intentionally retains
legacy values; preparation diagnoses them rather than inventing defaults.
Unrelated out-of-scope cell values are not validated, but required reference
rows must also be representable. Formula-like strings remain literal strings;
the populated XLSX writer must retain literal text handling when saving them.

`WorkbookExportError` reports the first defect with sheet, database ID when
available, and column. It does not return partial export frames. Invalid
`site_ids` arguments raise ValueError. Preparation checks representability and
reference integrity, not every CONFIG semantic constraint. Coordinate/interval
consistency, overlap checks and eventual plan applicability remain authoritative
in the subsequent CONFIG validation/planning workflow. Initial-label selection
does not establish that the whole label history is valid.

This step prepares in-memory workbook values only. It does not compare an edited
workbook with the database, generate YAML, apply changes or write a populated
XLSX file. Pass its result to the G2.d writer below.

```bash
pytest -q tests/test_configuration_workbook_preparation.py
pytest -q tests/test_configuration_workbook*.py
```

## Populated workbook writing (G2.d)

```python
from pathlib import Path

from dendroflow.configuration.workbook.preparation import prepare_workbook_export
from dendroflow.configuration.workbook.source import read_configuration_frames
from dendroflow.configuration.workbook.writer import write_workbook_export

frames = read_configuration_frames()
export = prepare_workbook_export(frames)  # all records; or site_ids=[actual_site_id]
path = write_workbook_export(
    Path.home() / "Downloads" / "dendroflow-control.xlsx",
    export,
    target_environment="local-dev",
)
print(path)
```

Use the non-secret environment label agreed for your database pair. The output
directory must exist and the filename must be new. Preparation can reject legacy
records that the workbook cannot represent; resolve those diagnostics explicitly
instead of silently changing database values just to make an export succeed.

The saved workbook contains all eleven resource sheets in schema order, with
prepared row order, IDs, aliases, roles and relationship references intact.
Reference rows are shaded grey; filters and frozen headers help navigation.
Dropdowns and shading are editing aids, not access controls. Empty sheets still
contain all headers. Nullable values are blank; FALSE remains a boolean value.
IDs, timestamps, JSON and ordinary strings are literal text, including strings
beginning with `=` and Excel error-looking text. Numeric fields use decimal text
as described above, preventing export rounding from creating apparent edits.

Every saved export gets a new UUID, its scope, selected IDs as a JSON array of
decimal strings, and an aware UTC export timestamp. By default `exported_at`
records file-generation time. Callers can pass an aware Python `datetime` through
the `exported_at` keyword; it is normalized to UTC. Neither value establishes an
atomic database snapshot, reserves database state, or proves workbook freshness.

The writer consumes `WorkbookExport` from preparation without changing its
frames or opening database connections. It checks its structural boundary
(sheets, headers, IDs, roles, scope and Excel row limits) and cell storage types
because callers can mutate the prepared frames. It does not repeat reference
closure or full CONFIG validation. Pass the unmodified preparation result;
this API is not an import validator for arbitrary edited frames.

As with templates, existing files are never overwritten. The workbook is
serialized in memory before the new output file is opened. Serialization errors
leave no output file; filesystem write errors can leave an incomplete new file.
No YAML is generated and no database changes are applied by exporting.

```bash
pytest -q tests/test_configuration_workbook_export.py
pytest -q tests/test_configuration_workbook*.py
```

Tests save and reopen actual XLSX files, checking values, metadata, formatting,
scope, literal text, error handling and input preservation. Also open a local
export in Excel or LibreOffice to inspect usability. G3-G6 will verify reading,
comparison and the unchanged-export/no-database-writes acceptance case.

## Workbook structure and metadata reading (G3.a)

```python
from pathlib import Path

from dendroflow.configuration.workbook.reader import WorkbookReadError, read_workbook

try:
    document = read_workbook(
        Path.home() / "Desktop" / "dendroflow-control.xlsx",
        expected_environment="local-dev",
    )
except WorkbookReadError as error:
    for issue in error.issues:
        print(issue.sheet, issue.coordinate, issue.message)
else:
    print(document.metadata)
    for sheet_name, rows in document.sheets.items():
        print(sheet_name, len(rows))
```

`read_workbook()` accepts an existing `.xlsx` path and expands `~` in string
paths. It opens the file without modifying it and closes it before returning.
It uses openpyxl with formula expressions retained, rather than cached results.
The workbook is loaded in memory; this API is intended for configuration data,
not measurement tables. It does not connect to databases, evaluate formulas,
generate YAML or apply changes.

The structural checks require `workbook_info` and all eleven resource sheets,
including empty ones. `guide` is optional and its content is ignored. Sheet,
column and metadata-key order may change. Names are exact and case-sensitive;
missing/unknown sheets, missing/unknown/duplicate headers, non-text headers,
merged cells outside the guide, chart sheets outside the guide, and populated
cells without a header are errors. Extra blank formatted columns are ignored.
Entirely blank or whitespace-only rows are ignored without renumbering surviving
cells. Hidden sheets and rows are read normally; hiding is not exclusion.

Every metadata key must occur exactly once. Values must satisfy this contract:

- `format_version` is integer 1, not text or a boolean.
- `workbook_id` is UUID text.
- `target_environment` is a nonblank label without surrounding whitespace or
  control characters, at most 128 characters, exactly matching the caller's
  `expected_environment` label. That argument is mandatory and similarly checked.
- `scope` is `all`, `sites` or `template`.
- `site_ids` is a JSON array of unique positive BIGINT decimal strings; it is
  nonempty only for `sites`. Leading-zero IDs are rejected. Returned IDs are
  sorted Python integers. Their existence and correspondence to resource rows
  are checked in later phases, not by this reader.
- `exported_at` is blank for templates; exports require ISO 8601 UTC text with
  `T`, seconds, optional microseconds, and `Z` or `+00:00`. Native Excel date
  cells, naive timestamps and non-UTC offsets are rejected in this metadata field.

Metadata keys, values and headers cannot be formulas or Excel errors. The
environment check compares explicit labels; it does not verify live connection
identity or workbook authenticity. Export time does not guarantee freshness.

The result is a `WorkbookDocument` containing parsed `WorkbookMetadata` and
`sheets`. Each resource sheet maps to a tuple of row dictionaries keyed by schema
column name. Each entry is a `WorkbookCell` with `sheet`, original Excel
`coordinate`, raw `value` and openpyxl `data_type`. Sheet and dictionary column
order follow the schema; resource row order follows the file. Dictionaries are
caller-owned and mutable. No openpyxl worksheet or live file handle is returned.

For example, `document.sheets["sites"][0]["name"].coordinate` identifies the
actual cell even after columns or rows have moved. Values such as `000001`,
`NA`, `NULL`, FALSE, zero, decimal text, whitespace and blank cells are preserved
without pandas type inference. Raw cells can subsequently become normalized
DataFrames through G3.b while retaining these locations for diagnostics.

**A successful structural read is not resource validation.** Resource formulas,
Excel errors, dates, invalid IDs and missing relationships remain represented
in the raw document. Run G3.b to check formulas/errors and parse cells before
comparison; G3.c checks identities, relationships, roles and initial labels.
Literal strings beginning with `=` remain distinguishable from Excel formulas.
Existing CONFIG validation and planning remain necessary before any apply.

`WorkbookReadError.issues` contains sheet/cell diagnostics. Structural defects
are collected together; metadata value checks report the first invalid value
after checking key structure. Missing headers/keys or unreadable files may have
no cell coordinate. No partial document is returned. Invalid caller environment
arguments raise `ValueError` before reading the file.

```bash
pytest -q tests/test_configuration_workbook_reader.py
pytest -q tests/test_configuration_workbook*.py
```

Tests read saved templates and populated exports, exercise reordered structures,
hidden and blank rows, corrupt files, metadata failures and raw cell preservation.
Workbook validation CLI wiring remains for G5.

## Resource cell parsing (G3.b)

```python
from dendroflow.configuration.workbook.parsing import WorkbookParseError, parse_workbook
from dendroflow.configuration.workbook.reader import read_workbook

document = read_workbook(
    "~/Desktop/dendroflow-control.xlsx",
    expected_environment="local-dev",
)
try:
    parsed = parse_workbook(document)
except WorkbookParseError as error:
    for issue in error.issues:
        print(issue.sheet, issue.coordinate, issue.message)
else:
    print(parsed.frames["sites"])
    print(parsed.coordinates["sites"])
```

Pass the unmodified result of `read_workbook()`. The parser performs no file or
database IO and leaves the raw document unchanged. It returns `ParsedWorkbook`
with the same metadata, eleven value `frames`, and eleven matching `coordinates`
frames. Each DataFrame uses object dtype, schema column order and a fresh
positional row index in workbook order; empty sheets still retain their columns.
This preserves Python integers, None, booleans and aware datetimes without
pandas converting mixed null/ID columns to floats or null dates to NaT.

For example, `parsed.coordinates["sites"].at[0, "name"]` identifies the physical
Excel cell that supplied `parsed.frames["sites"].at[0, "name"]`, even if the user
reordered columns or left blank rows. The returned frames and JSON objects are
caller-owned and mutable. They are not a stored baseline or an executable plan.

Cell parsing follows these rules:

| Kind | Accepted input and returned value |
| --- | --- |
| Blank | None, empty strings and whitespace-only strings become None only for nullable fields; required blanks are errors |
| Text/reference | Text is trimmed at its edges; case, internal whitespace, Unicode, leading zeros, `NA` and `NULL` remain literal; numbers/dates/booleans are not converted to text |
| Database ID | Blank for a new row, otherwise positive BIGINT decimal **text** with no leading zeros; returned as an exact Python int |
| Number | Native Excel int/float or decimal text with a dot separator and optional scientific notation; returned as a finite Python float; booleans, non-finite values, overflow and nonzero values that underflow to zero are rejected |
| Boolean | Native boolean, case-insensitive TRUE/FALSE text, or a boolean cell containing exactly the constant formula `=TRUE()`/`=FALSE()`; returned as Python bool; 0/1 and yes/no are rejected |
| Timestamp | ISO 8601 text with `T`, seconds, up to six fractional digits, and `Z` or a signed HH:MM offset; returned as a UTC Python datetime preserving microseconds |
| JSON | JSON object text becomes a fresh dict; nested arrays retain order and JSON strings retain their contents; duplicate keys at any level, non-finite numbers and scalar/array roots are rejected |

Database IDs require text even when a small numeric Excel cell would currently
be exact. This avoids accepting IDs whose digits Excel might already have
rounded. Restore an affected ID from a fresh export; formatting an already
rounded numeric cell as text cannot recover it. Coordinates, height and azimuth
can accept native numbers, but retain exported decimal text for an unchanged
round trip.

Formula cells and Excel error cells are checked before blank handling, including
in nullable fields. The only formula exception is an exact `=TRUE()` or
`=FALSE()` in a BOOLEAN column, ignoring case and surrounding whitespace.
LibreOffice can save native boolean values in this form during an unchanged
XLSX round trip. The parser recognizes these constants directly; it neither
evaluates formulas nor reads cached results. Cell references, arguments,
operators, compound expressions, and constant formulas in other column kinds
remain errors. A text cell containing `=TRUE()` is still literal text, not a
boolean; ordinary TRUE/FALSE text remains accepted in boolean columns.

Native Excel date/time cells are rejected rather than given
an inferred timezone. Literal strings beginning with `=` or looking like
`#REF!` are retained when their Excel cell type is text. Text must also fit the
XLSX cell limit and supported character set. No formulas are evaluated.

`row_role` must be exactly `edit` or `reference`, and `reader_type` must be
`csv`. These are value checks only: permission to edit a particular resource,
the meaning of an existing ID, and whether references resolve are not decided
here. JSON objects are parsed without defaulting or interpreting reader options.

`WorkbookParseError.issues` collects invalid cells in schema, row and column
order, with field names and original coordinates. No partial result is returned
if any cell fails. G3.a reading errors remain `WorkbookReadError`; malformed
caller-created documents are outside the intended API input.

Successful parsing still requires the G3.c identity, relationship, role and
initial-label checks below. Coordinate pairs/ranges, intervals, timezone names,
database conflicts and eventual plan applicability remain subject to subsequent
validation and the existing CONFIG workflow. This step does not generate YAML,
compare against the database, or authorize an apply.

```bash
pytest -q tests/test_configuration_workbook_parsing.py
pytest -q tests/test_configuration_workbook*.py
```

Tests cover saved template/export reading followed by parsing, reordered-cell
provenance, null and scalar rules, precision boundaries, nested JSON, aggregated
diagnostics and input/output independence. The complete unchanged-workbook to
zero-write plan/apply acceptance case remains for G4-G6.

## Workbook consistency validation (G3.c)

```python
from dendroflow.configuration.workbook.parsing import parse_workbook
from dendroflow.configuration.workbook.reader import read_workbook
from dendroflow.configuration.workbook.validation import (
    WorkbookValidationError,
    validate_workbook,
)

parsed = parse_workbook(read_workbook(
    "~/Desktop/dendroflow-control.xlsx",
    expected_environment="local-dev",
))
try:
    validate_workbook(parsed)
except WorkbookValidationError as error:
    for issue in error.issues:
        print(issue.sheet, issue.coordinate, issue.message)
else:
    print("Workbook consistency checks passed. Database state was not checked.")
```

`validate_workbook()` accepts an unmodified `ParsedWorkbook`, returns None on
success, and raises `WorkbookValidationError` with located `issues` on failure.
It performs no file or database IO and does not modify values or coordinates.
Rows and columns may be reordered as long as their coordinate frames stay
aligned. The public workflow remains read, parse, validate; this function does
not repeat G3.a/G3.b scalar validation or validate arbitrarily constructed frames.

The identity and relationship checks:

- Require every nonblank database ID to be unique within its sheet. Multiple
  blank IDs remain valid candidates for new resources.
- Require each trimmed, case-sensitive `ref` to be unique within its sheet.
  The same alias can occur in different sheets.
- Resolve every nonblank relationship through the schema's target sheet.
  Missing and ambiguous references are errors; duplicate aliases are never
  resolved by choosing the first row.
- Reject self-links and longer cycles in site ancestry.

These checks do not verify that an ID exists in the database. G4 must reject
stale or invented IDs instead of replacing them with CREATE operations.

Workbook role and scope checks follow this table:

| Scope/row | Required role and restriction |
| --- | --- |
| template | Blank database IDs and `edit` roles for every resource row |
| all | Every included row has role `edit`; existing and new rows are allowed |
| sites: selected existing sites | Selected IDs must be represented in `sites`, with role `edit` |
| sites: ancestor sites | Existing required ancestors have role `reference`; new sites require all/template scope |
| sites: locations, labels, deployments, interfaces | Role `edit`; the workbook ownership chain must end at a selected site |
| sites: shared catalogue/instrument/file rows | Existing rows have role `reference`; new supporting rows have role `edit` |

For a site export, each shared or ancestor row must be reachable as a dependency
of a selected site or one of its locations, labels, deployments or interfaces.
Unrelated existing rows and unattached new catalogue/file rows require a broader
scope. Following an interface to its file never includes other interfaces from
that shared file. Selected site rows remain necessary scope anchors even when
the user omits other records.

This is a check of the workbook's declared relationships only. A user can edit a
relationship to make an unrelated existing record appear to belong to a selected
site. **G4 must independently check current database ownership and row roles**,
as well as differences on reference rows, before emitting YAML. G3.c success
does not grant permission to update a resource or prove that an edit is supported.

Initial-label and file checks:

- Each new location requires exactly one associated new label with
  `is_initial=TRUE`. Additional new labels must use FALSE. Existing label IDs
  cannot be attached to a new location.
- A new label attached to an existing location must have `is_initial=FALSE`.
- More than one initial marker among the included labels of any location is
  an error. Existing locations do not require their initial-label row to remain
  in the workbook: omission is not deletion. G4 must compare each included
  existing label and its helper marker against current database state.
- Each new file requires at least one associated new interface. An existing
  interface cannot supply that requirement because RAW UPDATE is unsupported.
  Existing unreferenced files remain valid in all scope.

The validator collects issues by check stage, using schema and workbook row
order within each stage. Every duplicate participant is reported. Missing
selected sites are reported against `workbook_info` without inventing a cell
coordinate. Other issues retain the original cell coordinates through G3.b.

Unchanged exported workbooks should pass these offline checks. This does not
prove that existing immutable values are unchanged, check every CONFIG semantic
constraint (such as ranges or validity overlaps), generate YAML or authorize
apply. G4 and the existing CONFIG validation/planning pipeline remain required.
Missing rows never generate deletion requests.

```bash
pytest -q tests/test_configuration_workbook_validation.py
pytest -q tests/test_configuration_workbook*.py
```

Tests cover the real export/read/parse/validate path, every reference column,
duplicate identities, site ancestry, site scope, shared dependencies, initial
labels, new files, missing rows, reordered frames and absence of external IO.

## Current database matching (G4.a)

`match_workbook(parsed, current_frames)` validates the workbook and matches every nonblank workbook ID against a fresh database-shaped source snapshot. Existing IDs that are missing or outside the current selected-site ownership closure raise located `WorkbookMatchError` issues. Blank IDs remain declaration candidates with no promised INSERT action. Omitted rows remain absent from the comparison and never request deletion.

`read_workbook_matches(parsed)` obtains fresh read-only configuration frames through `read_configuration_frames()` and then performs the same checks. The result retains workbook values, cell coordinates, current database rows, and the role required by current scope for G4.b field comparison. It does not persist a baseline or authorize an apply.

## Field comparison (G4.b)

```python
from collections import Counter

from dendroflow.configuration.workbook.comparison import compare_workbook
from dendroflow.configuration.workbook.matching import read_workbook_matches
from dendroflow.configuration.workbook.parsing import parse_workbook
from dendroflow.configuration.workbook.reader import read_workbook

parsed = parse_workbook(read_workbook(
    "~/Desktop/dendroflow-control.xlsx", expected_environment="local-dev",
))
matched = read_workbook_matches(parsed)
comparison = compare_workbook(matched)
print(dict(Counter(row.status.value for rows in comparison.rows.values() for row in rows)))
for issue in comparison.issues:
    print(issue.sheet, issue.coordinate, issue.message)
comparison.raise_for_errors()
```

`compare_workbook()` accepts an unmodified `MatchedWorkbook` from G4.a. It
performs no IO and does not modify its inputs. G4.a remains responsible for
identity matching and current scope verification. The report uses the snapshot
supplied to G4.a; call `read_workbook_matches()` again when a fresh read is needed.
The environment label does not configure or authenticate database connections.

Each `comparison.rows[sheet]` entry contains a detached `match`, a `status`,
`changes`, and located `issues`. Rows remain in schema/workbook order, and fields
are compared in schema order regardless of displayed Excel column order.

| Status | Meaning |
| --- | --- |
| `unchanged` | Included existing fields equal current database values |
| `new` | Blank-ID declaration candidate; subsequent CONFIG resolution may reuse a compatible record |
| `update` | An editable existing row differs only in fields exposed by the public YAML update model |
| `blocked` | A reference row differs, an unsupported existing field differs, or a required current value cannot be compared faithfully |

`WorkbookFieldChange` retains `field`, original `coordinate`, `update_field`,
`before`, and `after`. It includes both supported and blocked differences for
review. `update_field` follows the versioned workbook schema. A blocked row
never becomes a partial update, and must not be converted into a replacement
declaration. `comparison.issues` aggregates every blocking issue; call
`comparison.raise_for_errors()` before any later conversion. It raises
`WorkbookComparisonError` carrying those issues. The report itself is returned
even when blocked, so users can inspect all differences together.

Comparison rules:

- Existing relationships compare by target sheet and database ID. Alias edits,
  row/column reordering, and renaming a referenced resource's descriptive or
  natural-key fields do not themselves change the relationship.
- Relationship differences carry `WorkbookReference` values. Existing targets
  contain `sheet` and `database_id`, with no alias. New targets contain `sheet`
  and `ref`, with no database ID. They remain unresolved declaration references;
  G4.b does not guess natural-key matches or promise a CREATE operation.
- Blank nullable values are explicit nulls. Zero and FALSE remain real values.
  Finite numbers compare exactly, with no tolerance that could hide a real edit.
  Timestamps compare after UTC normalization.
- Reader options compare as JSON structures: object-key order is immaterial,
  array order matters, and booleans remain distinct from numbers (TRUE versus 1).
  Integer and float representations of the same JSON number compare equal.
  File `path`, `reader_type`, and `reader_options` are mapped to their stored
  `filepath` and `reader_config` fields before comparison.
- Existing `is_initial` markers are recomputed from the complete current label
  history using `(valid_from, location_label_id)`, including omitted workbook
  labels. Changes to the helper marker or existing label fields are blocked.
- Current values must satisfy workbook representability checks. Invalid legacy
  text, types, timestamps, or reader settings produce located diagnostics;
  comparison does not silently normalize them. Invalid unrelated scalar values
  are not inspected. Required label history is inspected even when omitted.
- Missing rows never request deletion. Reference rows must match current values,
  including fields that are editable in a broader scope. G4.a's existing scope
  restrictions remain unchanged.

The report is not a resolved CONFIG plan. An `update` status describes field
support, not full semantic validity or guaranteed applicability. Coordinate
pairs/ranges, validity intervals, uniqueness, selector ambiguity, declaration
reuse, and resulting operations still require later CONFIG validation and
planning. G4.c-G4.f must verify selectors and generated operations before YAML
is considered ready. Successful comparison does not authorize apply.

An unchanged export should contain only `unchanged` rows and no field changes.
The later end-to-end assertion of zero CREATE/UPDATE operations remains for
G4.f. Database edits since export can appear as requested changes back to the
workbook values: there is no export-time baseline or editing-history detection.

```bash
pytest -q tests/test_configuration_workbook_comparison.py
pytest -q tests/test_configuration_workbook*.py
```

## Existing-resource selectors (G4.c)

```python
from dendroflow.configuration.workbook.matching import read_workbook_matches
from dendroflow.configuration.workbook.parsing import parse_workbook
from dendroflow.configuration.workbook.reader import read_workbook
from dendroflow.configuration.workbook.selectors import build_workbook_selectors

parsed = parse_workbook(read_workbook(
    "~/Desktop/dendroflow-control.xlsx", expected_environment="local-dev",
))
matched = read_workbook_matches(parsed)
verified = build_workbook_selectors(matched)
for sheet, selectors in verified.selectors.items():
    for database_id, selector in selectors.items():
        print(sheet, database_id, selector.alias,
              selector.lookup.model_dump(exclude_none=True))
```

`build_workbook_selectors()` accepts an unmodified G4.a `MatchedWorkbook`, runs
G4.b on that same snapshot, and rejects blocked comparisons before building
selectors. It performs no file or database IO. The returned `WorkbookSelectors`
contains a `selectors[sheet][database_id]` mapping for the nine resources with
public lookup models. Each `WorkbookSelector` includes its current identity,
alias, public Pydantic `lookup` model, dependency keys `(sheet, database_id)`,
and a `helper` flag for omitted current dependencies. Result mappings/models
are caller-owned. Database IDs are internal verification evidence, not public
YAML lookup fields.

The builder uses the complete current identifying fields exposed by CONFIG:

| Resource | Public lookup fields from current database state |
| --- | --- |
| sites | `site_code` |
| location_types, sensor_types | `type` |
| variables | `variable` |
| sensor_models | `manufacturer`, `model` |
| sensors | `serial_number`, reference to current `sensor_model` |
| locations | Reference to current `site`, earliest `initial_label` text |
| deployments | References to current `sensor`, `location`, `variable`, plus `valid_from` |
| files | `path` from stored `filepath` |

Existing location-label and interface rows have no public lookup models and
remain comparison context. Blank-ID rows remain new declaration candidates and
receive no existing selector. An all-new template yields empty selector maps.

Selectors always describe the current record. A site-code rename selects the
old site code; a sensor-model reassignment selects the current model; a
deployment date change selects the current start instant. Proposed values are
retained in G4.b and belong in later explicit updates, not in the lookup.

Selector dependencies can require records omitted from the edited workbook.
The builder follows current database IDs recursively and creates helper aliases
for those records. It reuses an included existing row's workbook alias when
available. Generated aliases use `current_<resource>_<id>`, with deterministic
numeric suffixes to avoid collisions with any existing or new workbook alias
in the same resource namespace. A dependency is always an existing reference;
it must not accidentally bind to a new declaration that replaced the old row.
Helpers are lookup context only: they do not broaden edit scope or request
changes to omitted resources. Row/column reordering does not change selectors.

Verification compares all supplied selector predicates against the full G4.a
snapshot, including records absent from the workbook or outside its selected
site scope. The candidate IDs must be exactly the intended ID. Full composite
selectors distinguish repeated serial numbers across models and repeated
initial labels across sites. Duplicates that remain ambiguous are errors; the
builder does not pick the first row or add unsupported lookup fields (such as
deployment `valid_to`) to distinguish them.

Initial labels come from complete current history ordered by `valid_from` then
`location_label_id`, even if every label row was omitted from the workbook.
An intended location without a label cannot be expressed with this lookup.
Unlabeled candidate locations are excluded consistently with CONFIG's lateral
inner join. Deployment timestamps are normalized to UTC instants. Identity
text is checked before constructing lookup models, so automatic whitespace
normalization cannot silently change what is selected.

Failures raise `WorkbookSelectorError` with located `issues`; no partial result
is returned. Errors point to the existing workbook row's ID cell. A failed
omitted dependency is reported at its dependent workbook row, naming the
current dependency ID. G4.b blocking errors remain `WorkbookComparisonError`.

File selectors require special handling in the next step. G4.c returns a
`FileLookupConfig` as identity evidence, but the existing CONFIG resolver does
not execute `references.files`. G4.d must put new interfaces for an existing
file into a compatible file declaration using current file settings. It must
verify reuse of the intended file, rather than treating a returned lookup model
as proof that an executable file-reference workflow exists.

This step verifies selector uniqueness in the supplied snapshot. It does not
query PostgreSQL again, generate a complete CONFIG document, or verify a future
apply. G4.f must resolve generated CONFIG against live databases and check
target IDs and operations again. The source reader's separate database
transactions and absence of an export-time baseline remain unchanged.

```bash
pytest -q tests/test_configuration_workbook_selectors.py
pytest -q tests/test_configuration_workbook*.py
```

## CONFIG model generation (G4.d)

```python
from dendroflow.configuration.workbook.configuration import generate_configuration
from dendroflow.configuration.workbook.matching import read_workbook_matches
from dendroflow.configuration.workbook.parsing import parse_workbook
from dendroflow.configuration.workbook.reader import read_workbook

parsed = parse_workbook(read_workbook(
    "~/Desktop/dendroflow-control.xlsx", expected_environment="local-dev",
))
generated = generate_configuration(read_workbook_matches(parsed))
print(generated.config.model_dump(exclude_defaults=True))
```

`generate_configuration(matched)` runs G4.b and G4.c against the supplied
G4.a snapshot, then assembles and validates a public `ConfigModel` with the
existing CONFIG validator. It performs no file/database IO and emits no YAML.
The returned `GeneratedConfiguration` contains the model, comparison report,
and verified selectors used to create it. A G4.b blocker or a model/CONFIG
validation error raises `WorkbookConfigurationError` or the existing
`WorkbookComparisonError`; no partial model is returned. Configuration errors
carry `WorkbookIssue` records when an originating workbook cell is known.

Existing records become `references` entries using G4.c's current-value
selectors. New rows become normal CONFIG declarations with their workbook refs.
Supported changes on editable rows become `updates` with the current selector
in `update` and workbook values in `set`. Nullable clears remain explicit nulls.
The original site code, serial number, model identity, deployment start, and
other current selector values therefore keep updates bound to the original row.
Unsupported edits and changes on reference rows stop generation.

New location declarations contain their one initial label as nested
`initial_label`. Additional new noninitial labels remain in top-level
`location_labels`; the nested initial row is omitted there. Existing labels and
interfaces are comparison context and are not redeclared.

Files require special composition because CONFIG has no executable
`references.files` workflow. If a new interface uses an existing file, G4.d
emits a file declaration with that file's current path, timestamp settings,
reader settings, and a stable alias. The normal CONFIG resolver can then reuse
the existing file and create the interface. New files and their new interfaces
are emitted together. Multiple new interfaces for one file share one file
declaration. G4.d does not change existing files or interfaces.

Current dependency rows, including helper aliases for omitted records, remain
lookups in `references`; they do not become edits. The generated model is
validated for CONFIG structure and semantics, but compatible-resource reuse,
live selector targets, and final CREATE/REUSE/UPDATE operations are not yet
verified here. G4.e adds validated YAML serialization; G4.f must resolve the
serialized configuration and compare targets and operations against the intended workbook changes. A new declaration is only a
candidate: the resolver may choose REUSE. Missing workbook rows never generate
deletions.

```bash
pytest -q tests/test_configuration_workbook_configuration.py
pytest -q tests/test_configuration_workbook*.py
```

Tests cover unchanged reference-only workbooks, supported updates, explicit
nulls, mixed additions and updates, nested initial labels, shared file reuse
declarations, new files/interfaces, site-scoped dependencies, templates,
validation diagnostics, deterministic output, and input preservation. Live
resolver operation checks remain for G4.e/G4.f.

Tests cover public lookup shapes, current-value renames, full-snapshot
ambiguity, omitted dependencies, alias collisions, initial-label history,
unchanged/scoped/new-only workbooks, original cell diagnostics, exact BIGINTs,
UTC dates, and input preservation. Compatibility tests exercise the real CONFIG
reference and update selector resolvers with mocked database lookups; live
PostgreSQL acceptance remains for G4.f.

## YAML serialization (G4.e)

```python
from dendroflow.configuration.workbook.serialization import serialize_configuration

serialized = serialize_configuration(generated.config)
print(serialized.yaml_text)
round_tripped_config = serialized.config
```

`serialize_configuration(config)` validates the public `ConfigModel`, emits
deterministic YAML using CONFIG field order, parses that YAML back into a model,
and validates it again. `SerializedConfiguration.yaml_text` is the YAML text;
`SerializedConfiguration.config` is the validated model reconstructed from
that text. The API performs no filesystem or database IO. Callers decide where
and when to save the text.

Serialization preserves explicitly supplied nullable fields, including
`null` values that request a clear in an UPDATE. Datetimes use the model's JSON
representation, and YAML strings such as `TRUE`, `NA`, or leading-zero IDs stay
strings. If serialization changes the model or either validation pass fails,
`WorkbookSerializationError` is raised and no text result is returned.

This step establishes the YAML boundary, but does not run database resolution.
G4.f verifies resolved targets and operations against the matched workbook and
current database state before the end-to-end acceptance workflow.

```bash
pytest -q tests/test_configuration_workbook_serialization.py
pytest -q tests/test_configuration_workbook*.py
```

Tests cover unchanged references, explicit null updates, nested declarations,
timestamps, YAML-sensitive strings, and deterministic repeated output.

## Resolver verification (G4.f)

```python
from dendroflow.configuration.workbook.verification import verify_generated_configuration

verified = verify_generated_configuration(generated)
print(verified.serialized.yaml_text)
for item in verified.plan.items:
    print(item.source_path, item.action.value, item.database_id)
```

`verify_generated_configuration(generated)` serializes and round-trips the
generated CONFIG, then calls the existing read-only CONFIG resolver using the
configured database connections. It returns the YAML and resolved plan only
after checking that current reference aliases bind to the database IDs verified
by G4.c, each supported workbook change resolves to an UPDATE of its original
ID with the same changed fields and values, and every declaration has exactly
one CREATE or REUSE operation. Declaration aliases must bind to those same
operations. A file declaration emitted for a new interface must REUSE the
workbook's intended existing file ID. A new workbook row may resolve to either
CREATE or compatible REUSE. An unchanged workbook must resolve to an empty
operation plan.

Resolver errors, missing or unexpected operations, wrong targets, and
unexpected changes raise `WorkbookPlanVerificationError`; its `plan` attribute
retains the blocked plan for diagnosis. The verifier performs no preparation,
confirmation, or database writes. The configured METADATA and RAW connections
must point to the target pair represented by `target_environment`; G5 will bind
that label to connection configuration.

```bash
pytest -q tests/test_configuration_workbook_verification.py
pytest -q tests/test_configuration_workbook*.py
```

Unit tests use controlled resolved plans to verify unchanged workbooks, scalar
and relationship updates, new declarations, existing-file reuse, wrong targets,
and resolver errors. Live database acceptance and export-to-apply checks remain
part of the later end-to-end verification.
