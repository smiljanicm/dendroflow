# DendroFlow RAW Ingestion

## Purpose

The RAW ingestion layer imports registered source files into the DendroFlow RAW database while preserving ingestion provenance and supporting safe restart after interruption.

RAW ingestion is responsible for:

- identifying the exact content of a source file
- reading files according to stored parser configuration
- mapping source columns to monitoring deployments
- interpreting source timestamps
- validating observations against deployment periods
- storing normalized RAW observations
- retaining physical source-line provenance
- processing large files in batches
- retrying failed batches
- resuming interrupted ingestion runs
- preventing accidental re-ingestion of an already completed file version

RAW ingestion does not perform scientific data cleaning, quality control, unit conversion, aggregation, or outlier handling. Those operations belong to the CLEAN processing layer.

---

## Data flow

The ingestion path is:

```text
registered file
      │
      ▼
file fingerprint
      │
      ▼
exact file version
      │
      ▼
source interfaces ──────► metadata deployments
      │
      ▼
ingestion run + immutable targets
      │
      ▼
tabular reader
      │
      ▼
physical batches
      │
      ▼
normalized observations
      │
      ▼
atomic RAW write
      │
      ▼
completed batches
      │
      ▼
successful interface markers
      │
      ▼
completed ingestion run
```

The main public entry point is:

```python
from dendroflow.ingestion import ingest_file

run = ingest_file(file_id)
```

`file_id` refers to a logical registered source file in the RAW database.

---

# Core concepts

## Logical files

The `files` table describes a source that DendroFlow knows how to read.

Conceptually:

```text
files
-----
file_id
filepath
timestamp_timezone
timestamp_format
reader_config
```

A file record is a logical source definition rather than a snapshot of one particular file content.

For example:

```text
/data/logger/Sandhagen_WaterTbl.dat
```

may remain the same logical source even though the file contents change over time.

The source definition also stores the information required to interpret the file:

- `filepath`
- `timestamp_timezone`
- `timestamp_format`
- `reader_config`

---

## File versions

Each ingestion begins by calculating the current file's SHA-256 fingerprint and size.

A version is stored in:

```text
file_versions
-------------
file_version_id
file_id
file_hash
file_size
discovered_at
```

The hash format is:

```text
sha256:<hexadecimal digest>
```

A logical file can therefore have many immutable content versions:

```text
files
  │
  ├── file_version A
  ├── file_version B
  └── file_version C
```

The combination:

```text
(file_id, file_hash)
```

is unique.

This distinction is important for reproducibility. `file_id` identifies the source; `file_version_id` identifies the exact bytes that were ingested.

---

## Reader configuration

Technical parsing behavior is stored in `files.reader_config` as JSON.

For example:

```json
{
  "reader": "csv",
  "options": {
    "skiprows": [0, 2, 3],
    "delimiter": ",",
    "encoding": "utf-8",
    "na_values": ["NAN"],
    "chunksize": 10000
  }
}
```

The current MVP supports the CSV-compatible reader backed by pandas.

Parser configuration describes how to read the tabular source. Scientific meaning is not stored in the reader configuration.

For example:

```text
reader_config
    → how to parse the file

sensor_file_interfaces
    → what individual columns mean
```

This separation allows technical file formats to change without embedding sensor semantics in parser code.

---

## Source interfaces

`sensor_file_interfaces` maps source columns to deployments.

Conceptually:

```text
sensor_file_interfaces
----------------------
interface_id
file_id
deployment_id
values_column
timestamp_column
unit
```

One interface represents one measurement column.

For a wide file:

```text
TIMESTAMP | temperature | water_level
```

DendroFlow may define:

```text
temperature  → deployment 21
water_level  → deployment 22
```

Each deployment identifies the corresponding sensor, location, variable, and validity period in the metadata database.

Because metadata and RAW are separate PostgreSQL databases, `deployment_id` is an application-managed cross-database reference rather than a PostgreSQL foreign key.

---

# Timestamp semantics

## Source timezone

`files.timestamp_timezone` describes the clock semantics of timestamps contained in the source file.

It should represent how the source logger or export process actually recorded time.

This is not necessarily the geographic timezone of the monitoring site.

For example, a logger physically located in Germany may record a fixed UTC+1 clock throughout the year. In that case a fixed-offset IANA timezone such as:

```text
Etc/GMT-1
```

is more accurate than:

```text
Europe/Berlin
```

because `Europe/Berlin` applies daylight-saving transitions that the logger did not use.

The source timezone should therefore be determined from source-system behavior, not simply from geographic location.

---

## Timestamp normalization

Source timestamps are parsed using:

```text
files.timestamp_format
files.timestamp_timezone
```

and converted into timezone-aware instants before insertion.

PostgreSQL stores observation timestamps as:

```text
TIMESTAMPTZ
```

The source timezone remains available in the file definition for provenance.

---

## Deployment validity

Every interface refers to a deployment with:

```text
valid_from
valid_to
```

An observation must satisfy:

```text
timestamp >= valid_from
```

and, when `valid_to` is present:

```text
timestamp < valid_to
```

An observation outside the deployment period causes normalization to fail rather than silently assigning the value to an invalid sensor-location-variable relationship.

---

# Physical source-line provenance

Every RAW observation records:

```text
source_row_number
```

This is the **1-based physical line number in the exact source file version**.

For example:

```text
line 1  metadata
line 2  column names
line 3  units
line 4  aggregation
line 5  first observation
```

the first parsed observation retains:

```text
source_row_number = 5
```

This makes it possible to trace a stored RAW value directly back to the corresponding line of the original file.

The reader calculates source-line provenance as a stream rather than materializing line numbers for the complete file in memory.

### MVP limitation

The provenance implementation assumes one parsed tabular record corresponds to one physical source line.

Multiline quoted CSV records are therefore outside the generic CSV reader contract for the current MVP.

---

# RAW observations

Normalized observations are stored in:

```text
raw_observations
----------------
observation_id
location_id
variable_id
timestamp
value
interface_id
ingestion_run_id
source_row_number
```

An observation retains multiple provenance paths.

Scientific identity:

```text
raw observation
      │
      ├── location_id
      └── variable_id
```

Source provenance:

```text
raw observation
      │
      ▼
interface
      │
      ▼
logical file
```

Execution provenance:

```text
raw observation
      │
      ▼
ingestion run
      │
      ▼
file version
```

Physical provenance:

```text
raw observation
      │
      ▼
source_row_number
```

The RAW database currently enforces uniqueness on:

```text
(location_id, variable_id, timestamp)
```

RAW therefore means that DendroFlow does not apply scientific cleaning transformations during ingestion; it does not mean that every possible duplicate source record can coexist independently of database identity constraints.

---

# Ingestion runs

An ingestion run represents one execution of RAW ingestion.

```text
ingestion_runs
--------------
ingestion_run_id
started_at
finished_at
status
```

Run status is one of:

```text
running
completed
failed
```

A new run is created only after the current file version and target interfaces are known.

---

# Ingestion targets

`ingestion_targets` records the immutable intention of an ingestion run.

```text
ingestion_targets
-----------------
ingestion_run_id
file_version_id
interface_id
```

Conceptually:

```text
ingestion_targets = what this run intends to ingest
```

Targets are created in the same database transaction as the ingestion run.

This means that even if the process terminates immediately after run creation, the database retains the exact intended:

```text
file version + interface set
```

That snapshot is used when deciding whether an interrupted run can safely be resumed.

---

# Ingestion batches

Large source files can be processed incrementally.

Each physical processing block is represented by:

```text
ingestion_batches
-----------------
ingestion_batch_id
ingestion_run_id
file_version_id
batch_number
source_line_start
source_line_end
row_count
status
attempt_count
started_at
finished_at
error_message
```

A batch represents a block of source records, not a set of individual observations.

For a two-interface source file, a batch containing 1,000 parsed rows may produce 2,000 RAW observations.

---

## Batch states

A newly created batch begins as:

```text
pending
```

Before processing:

```text
pending
   │
   ▼
running
```

A successful transaction produces:

```text
running
   │
   ▼
completed
```

A failed attempt produces:

```text
running
   │
   ▼
failed
```

A failed batch may be retried:

```text
failed
   │
   ▼
running
```

`attempt_count` is incremented each time the batch enters the running state.

The default ingestion limit is three attempts per batch.

---

# Atomic batch writes

Observation insertion and batch completion occur in the same PostgreSQL transaction.

Conceptually:

```text
BEGIN

insert RAW observations
mark batch completed

COMMIT
```

This prevents a batch from being marked successful when its observations were not committed.

If the transaction fails, neither the observation insertion nor the completed checkpoint should survive independently.

---

# Resume behavior

Restartability is based on the exact:

```text
file_version_id + target interface set
```

DendroFlow resumes only a `running` ingestion run whose targets exactly match the current ingestion request.

A terminal `failed` run is not automatically revived.

---

## Completed batches

When an existing batch checkpoint is found with:

```text
status = completed
```

DendroFlow validates that the stored checkpoint still corresponds to the current source-line range and row count.

If it matches, that batch is skipped.

Its observations are not written again.

---

## Interrupted running batches

If a resumed run contains a batch with:

```text
status = running
```

DendroFlow treats that state as evidence that the previous process was interrupted.

The batch is first marked failed:

```text
running
   │
   ▼
failed
```

and is then retried normally.

For example:

```text
batch 1  completed  attempt 1   → skipped
batch 2  running    attempt 1   → interrupted
                                  ↓
                                failed
                                  ↓
                                running attempt 2
                                  ↓
                                completed
batch 3  absent                 → created and processed
```

This behavior assumes one ingestion worker per file/run in the current MVP.

Concurrent workers processing the same ingestion run are not currently part of the supported execution model.

---

# Successful interface markers

`ingestion_interfaces` records successful completion.

```text
ingestion_interfaces
--------------------
ingestion_run_id
file_version_id
interface_id
```

Conceptually:

```text
ingestion_targets
    = intention

ingestion_batches
    = progress and retry history

raw_observations
    = imported data

ingestion_interfaces
    = successful completion

ingestion_runs
    = execution lifecycle
```

Interface success markers are created only when all batches in the run have completed successfully.

Finalization then changes the run from:

```text
running
```

to:

```text
completed
```

as part of the same finalization transaction.

---

# Re-ingestion and idempotency

Before creating a new run, DendroFlow checks whether the exact file version has already been successfully ingested for the requested interfaces.

If a matching completed run exists:

```python
ingest_file(file_id)
```

returns that completed run without inserting another copy of the observations.

Therefore repeated ingestion of an unchanged source file is a no-op.

If only part of the requested interface set has already been successfully ingested, the current MVP rejects the operation rather than attempting implicit selective ingestion.

---

# Failure behavior

When an ordinary ingestion error exhausts retries, the ingestion run is marked:

```text
failed
```

The original exception is then propagated to the caller.

Examples of failures include:

- missing source columns
- missing metadata deployments
- invalid timestamp parsing
- timestamps outside deployment validity
- database constraint violations
- exhausted batch retries

An unexpected process termination may instead leave the run or a batch in `running` state. That persistent state is what enables interruption detection and safe resume on the next invocation.

---

# Reader scalability

CSV input can be processed using `chunksize`.

When chunking is enabled:

```text
source file
    │
    ├── batch 1
    ├── batch 2
    ├── batch 3
    └── ...
```

DendroFlow does not need to load the full tabular dataset into memory.

Physical source-line provenance is also generated incrementally.

For integer `skiprows`, the reader compares physical line indexes directly rather than constructing a set containing every skipped row.

Memory usage therefore scales primarily with the configured batch size rather than the total number of rows in the source file.

---

# Current MVP scope

The RAW ingestion MVP currently supports:

- registered local source files
- CSV-compatible tabular input
- database-driven reader configuration
- multi-interface wide files
- SHA-256 file versioning
- chunked ingestion
- physical source-line provenance
- file-level timestamp parsing and timezone semantics
- deployment validity checks
- retryable ingestion batches
- interrupted-run resume
- completed-file idempotency
- PostgreSQL-backed provenance

The current MVP deliberately does not attempt to provide:

- automatic source discovery
- distributed ingestion workers
- concurrent ingestion of the same run
- multiline CSV provenance
- automatic selective repair of partially ingested interface sets
- scientific cleaning or quality-control rules
- unit conversion during RAW ingestion

These capabilities can be added later without changing the core distinction between source definition, exact file version, ingestion intention, processing progress, and successful completion.

---

# Implementation structure

RAW ingestion code is organized by responsibility:

```text
src/dendroflow/ingestion/
├── __init__.py
├── models.py
├── sources.py
├── normalization.py
├── versions.py
├── runs.py
├── batches.py
├── writer.py
└── service.py
```

Responsibilities are:

```text
models.py
    ingestion-domain data structures

sources.py
    files, interfaces, readers, and metadata deployments

normalization.py
    source rows → normalized RAW observations

versions.py
    file fingerprinting and immutable file versions

runs.py
    run lifecycle, targets, completion, and resume lookup

batches.py
    batch lifecycle and checkpoint validation

writer.py
    transactional RAW writes

service.py
    end-to-end ingest_file orchestration
```

The package `__init__.py` provides the stable public ingestion API while implementation responsibilities remain separated internally.

---

## Growing-file ingestion contract (GF1 design)

This section defines the intended behaviour for registered source files that
receive new rows over time. It is a design contract for the next implementation
phase; the current ingestion implementation does not yet support safe append
ingestion. The CONFIG MVP tag remains unchanged.

### Snapshot boundary

Each ingestion invocation processes one immutable snapshot of a registered
file. It fingerprints, reads, records provenance for, and resumes from the same
snapshot. Appends made after the snapshot boundary are handled by a later run.

For the initial implementation, a source is eligible for capture after its
size and modification time remain stable for a configured settle interval. The
capture records the initial file identity, size and modification time, copies
exactly the captured byte range into a persistent DendroFlow staging area, and
checks the source metadata again. A size decrease, file replacement, or change
during capture invalidates the capture; retry later or report that the source
is still changing. A snapshot is identified by its content hash and byte size.

Only newline-terminated physical records are eligible for parsing. An
incomplete trailing physical line is left for the next snapshot. This relies on
the supported CSV contract of one physical line per record; multiline quoted
CSV records remain unsupported. A later append must not alter bytes already
captured in a snapshot. Snapshots referenced by running or resumable ingestion
runs must remain available across process restarts. Remove a staged snapshot
only after no run can resume from it and its file version is retained in the
RAW database.

The staging area must be configurable, persistent across runs, and have
sufficient capacity for the largest source snapshot being ingested. Capture
must fail clearly if staging storage is unavailable or full. The settle
interval and staging location are operational settings, not workbook fields.

### Observation identity and overlap

The RAW database identity remains (location_id, variable_id, timestamp).
Compare incoming values after the existing timestamp and numeric normalization,
using exact equality of the normalized stored values. Two missing numeric values
(normalized to PostgreSQL NaN) compare equal. Do not use a numeric tolerance.

For each incoming identity:

| Existing RAW observation | Required result |
| --- | --- |
| No observation exists | Insert the observation with the new run and source-line provenance. |
| Same interface and equal normalized value | Count it as unchanged; do not insert or replace it. Keep its original provenance. |
| Different value | Report a data conflict with identity, incoming source line, stored value and incoming value; fail the current batch without overwriting the stored value. |
| Different interface | Report a source-mapping conflict; fail the current batch without changing the stored observation. |

Within one snapshot, repeated identities with equal values and the same
interface are counted once as an insert or unchanged observation; retain the
first physical source line and report the repeated rows. Repeated identities
with conflicting values or interfaces fail the batch as data conflicts.

All inserts and the batch completion checkpoint remain one transaction. If a
batch contains a conflict, none of that batch's inserts or checkpoint changes
commit. Earlier completed batches remain committed and visible. A retry must
not turn a deterministic conflict into a successful write; conflicts require
review and a new ingestion request after the source or configuration is
corrected.

### Growth, rewrite, and recovery

Appending complete rows creates a new file version and a new ingestion run. The
run compares observations already present in RAW against the new snapshot,
leaves matching overlaps untouched, and inserts only new observations. It must
not rely only on the last timestamp: late-arriving older observations can be
valid and must be considered.

A snapshot smaller than the latest accepted snapshot for the logical file is a
truncation or regression and is rejected for review; it never deletes RAW
observations. A changed value or source mapping for an already stored identity
is a conflict. This policy also detects rewritten historical content when the
rewritten row retains its observation identity. Corrections and deletion of
stored observations require a separately reviewed future workflow.

An interrupted run resumes against its retained snapshot and the exact
interface, timestamp, reader, and deployment interpretation captured for that
run. It must not switch to a newer live-file version while resuming. A later
append is processed in a separate run after the interrupted run completes.
Only one ingestion worker may process a given registered file at a time.

### Run results

A successful result reports at least the source file and snapshot hash, run ID,
interfaces, source rows examined, observations inserted, observations unchanged,
repeated identities, and any deferred trailing line. Failures report the
snapshot/run/batch where possible, the error category, and source line and
observation identity for data conflicts. These counts distinguish routine
append ingestion from corrections that need review.

### GF1 acceptance cases

The contract is accepted when automated unit and PostgreSQL integration tests
cover all of the following:

1. Ingest a 100-row snapshot, append 20 complete rows, ingest again, and finish
   with 120 unique observations. The original 100 keep their original
   provenance; the 20 new observations refer to the second snapshot and run.
2. Repeat an already ingested full snapshot: the second invocation is a no-op
   for observation writes and reports the overlap as unchanged.
3. Change the value of a previously ingested timestamp: report a conflict,
   preserve the stored value, and roll back every write in the conflicting
   batch.
4. Repeat an identity within one snapshot with equal and conflicting values;
   verify the deduplication and conflict rules above.
5. Capture a file with an incomplete final physical line, then append the rest
   of that record and a newline; ingest the record only from the later complete
   snapshot.
6. Truncate or replace a registered source while or after it is captured;
   reject the regressed or invalid capture and preserve all observations.
7. Interrupt a multi-batch run, append to the live file, then resume: finish
   the original snapshot exactly once and process the append as a separate run.
8. Attempt concurrent ingestion for one registered file; the second worker
   must exit with a clear already-running result and perform no writes.

These cases define scope for GF2-GF5. They do not claim that growing-file
behaviour is implemented until those phases and the real-source acceptance
check are complete.

---

# Testing

The ingestion layer has two levels of automated tests.

## Unit tests

The normal test suite runs without requiring a live database:

```bash
pytest
```

These tests cover readers, normalization, file versioning, runs, targets, batch lifecycle, writer behavior, and ingestion orchestration.

## PostgreSQL integration test

The integration test is opt-in because it requires migrated DendroFlow PostgreSQL databases:

```bash
DENDROFLOW_INTEGRATION=1 \
pytest tests/integration/test_raw_ingestion.py -m integration -v
```

The integration test verifies the complete interruption-and-resume path against the real PostgreSQL schema, including:

```text
run + targets
completed batch
interrupted running batch
resume
batch retry
remaining batches
RAW observation count
successful interface markers
run finalization
```

The test fixture removes its temporary database records after execution.