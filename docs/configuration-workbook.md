# CONFIG control workbook contract

## Status

G1 defines workbook format version 1, its sheet/column schema, and header checks.
G2.a adds an empty XLSX template writer using openpyxl. G2.b reads stored
configuration into pandas DataFrames. G2.c selects the export scope and prepares
workbook values and references. Populated workbook writing, workbook reading,
cell comparison, YAML generation, and workbook CLI commands remain for
subsequent G2-G5 steps.
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
It is provenance, not an authentication or permission mechanism. G2 must define
where this identifier is configured; it must not be inferred solely from the
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
  pairs and range constraints follow the existing CONFIG models.
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

G2.a adds template generation, G2.b adds database reading, and G2.c prepares the
export scope and workbook values. Remaining G2 work writes populated workbooks
and supplies their export metadata.
G3 reads and validates cells;
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

The output must use an `.xlsx` extension and an existing parent directory.
Existing files are never overwritten. Serialization finishes in memory before
opening the output file; an error during serialization creates no output.
Filesystem write failures can still leave an incomplete new file.

This step does not implement Excel import or database change planning. Inspect
the generated workbook in Excel or LibreOffice; do not expect edits to be
applied yet. Continue with a fresh database export once that capability exists.

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
XLSX file. Populated writing and environment/export metadata follow in G2.d.

```bash
pytest -q tests/test_configuration_workbook_preparation.py
pytest -q tests/test_configuration_workbook*.py
```
