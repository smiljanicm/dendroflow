# CONFIG control workbook contract

## Status

G1 defines workbook format version 1, its sheet/column schema, and header checks.
G2.a adds an empty XLSX template writer using openpyxl. Database export,
workbook reading, cell comparison, YAML generation, and workbook CLI commands
remain for subsequent G2-G5 steps.
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

G2.a adds template generation; remaining G2 steps add database export.
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
