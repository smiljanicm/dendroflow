# Ingestion CLI

The ingestion CLI runs RAW ingestion for registered source files. It uses the
current database target, which defaults to `local`, and the same source
configuration and ingestion service as the Python API.

## Commands

Run one file or several explicitly selected files:

```bash
dendroflow ingest --file-id 12
dendroflow ingest --file-id 12 --file-id 18
```

Run all registered files:

```bash
dendroflow ingest --all
```

The command requires exactly one selection mode: one or more `--file-id`
options, or `--all`. File IDs must be positive integers. Repeated IDs are
deduplicated and files are processed in ascending ID order. The command checks
that every explicitly selected ID is registered before it starts ingestion;
an invalid selection therefore cannot leave a partial run. `--all` with no
registered files reports an empty selection and succeeds.

Files run sequentially. A failure for one file does not prevent the remaining
selected files from running. Ingestion of each file uses the existing snapshot,
resume, retry, conflict, regression, and per-file locking behavior. The
`--max-attempts` option changes the existing per-batch retry limit and defaults
to `3`:

```bash
dendroflow ingest --file-id 12 --max-attempts 5
```

This command writes RAW data by design. It has no preview or confirmation
prompt; the selected IDs (or `--all`) are the operator's explicit request to
ingest.

## Per-file outcomes

Every selected file has exactly one outcome:

- `completed`: this invocation completed ingestion.
- `already_completed`: the current snapshot and interface set were already
  ingested; no new observations were written.
- `deferred`: work could not start or finish because the file was busy or its
  source did not settle. The error category identifies the reason.
- `needs_configuration`: the registered file has no source interfaces and
  needs CONFIG work before it can be ingested.
- `failed`: ingestion stopped for another error, such as a data conflict,
  source regression, database failure, or exhausted retry limit.

A deferred file can be retried on a later invocation. A failed file requires
review of its reported error before retrying. `needs_configuration` is reported
per file so other selected files can still complete; it makes the overall
command unsuccessful.

Typical results are:

- A first complete ingestion returns `completed` with its new run, version, and
  counts. If all selected files complete, the command exits `0`.
- Re-running the same snapshot returns `already_completed`, the existing run,
  and `null` counts. The command exits `0`.
- Resuming an interrupted run returns `completed` with `resumed: true`. Counts
  include successful batches committed by this invocation. The command exits
  `0` if all selected files complete.
- If a competing worker holds the file lock, that file returns `deferred` with
  error category `file_busy`. The command exits `3` if no file failed or needs
  configuration.
- If an overlapping observation has a different value, that file returns
  `failed` with error category `observation_conflict`. Earlier committed
  batches remain counted. The command exits `1`.
- If one file completes while another conflicts, the report includes both the
  `completed` and `failed` results, and the command exits `1`.

## Counts and provenance

Completed or failed work reports the file path, target environment, outcome,
run ID and, when known, file-version ID and snapshot SHA-256 hash. A resumed
run is marked `resumed: true`.

Counts describe this invocation, not lifetime totals for the file:

- `source_rows_examined`: parsed data rows yielded to the ingestion service,
  including rows in batches already completed by a prior invocation. Headers,
  configured skipped rows, and an incomplete trailing line are excluded.
- `observations_inserted`: RAW observations committed by successful batches
  during this invocation.
- `observations_unchanged`: incoming observations in successful batches that
  matched an existing RAW identity, interface, and value.
- `repeated_identity_rows`: extra rows within a reader batch that repeated the
  same observation identity, interface, and value and were deduplicated.
- `deferred_trailing_bytes`: bytes omitted because the captured source ended
  with an incomplete physical line. This is `0` when a new capture had no
  incomplete line, and `null` when this invocation reused a stored snapshot
  without capturing the live source.

The observation counts cover successful batches committed during this
invocation. They do not count batches committed by an earlier interrupted
invocation, and they exclude a batch whose transaction failed. A count is
`null` when the command could not measure it. `null` means unknown or not
applicable; it does not mean zero. For `already_completed`, counts are `null`
because the command does not reprocess the completed snapshot.

Each result also reports an error category and message when an outcome needs
attention. Batch number and physical source line are included when available.
The run ID, version ID, snapshot hash, and source-line context connect the
summary to database provenance; the CLI report is not a replacement for the
database records.

The stable error categories are `file_busy`, `source_changing`,
`needs_configuration`, `source_regression`, `observation_conflict`,
`database_error`, `retry_limit`, and `unexpected_error`. The human-readable
message may include details for an operator; automation should branch on the
category and outcome instead of parsing that message.

## Text and JSON output

Text output is the default for an operator at a terminal:

```text
File 12: completed
  Path: /data/logger.csv
  Run: 412; file version: 87
  Snapshot: sha256:...
  Rows examined: 120
  Observations: inserted=40, unchanged=200, repeated=0
```

Use `--json` when a script needs to read the results:

```bash
dendroflow ingest --all --json
```

JSON writes exactly one JSON object to standard output and no progress text.
The object has a `schema_version` of `1`, the `target_environment`, a `summary`
with counts for each outcome, and a `files` array with one result per selected
file. A result contains `file_id`, `filepath`, `outcome`, `ingestion_run_id`,
`file_version_id`, `snapshot_hash`, `resumed`, `counts`, and `error`. Fields
that are not known for an outcome are `null`.

Example:

```json
{
  "schema_version": 1,
  "target_environment": "local",
  "summary": {
    "selected": 1,
    "completed": 1,
    "already_completed": 0,
    "deferred": 0,
    "needs_configuration": 0,
    "failed": 0
  },
  "files": [
    {
      "file_id": 12,
      "filepath": "/data/logger.csv",
      "outcome": "completed",
      "ingestion_run_id": 412,
      "file_version_id": 87,
      "snapshot_hash": "sha256:...",
      "resumed": false,
      "counts": {
        "source_rows_examined": 120,
        "observations_inserted": 40,
        "observations_unchanged": 200,
        "repeated_identity_rows": 0,
        "deferred_trailing_bytes": 0
      },
      "error": null
    }
  ]
}
```

The `error` field is `null` on success. Otherwise it contains `category`,
`message`, `batch_number`, and `source_line`; the last two are `null` when
unavailable. JSON output does not include tracebacks or database credentials.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | All selected files completed or were already completed; an empty `--all` selection also succeeds. |
| `1` | At least one file needs configuration or failed for a non-deferred reason. |
| `2` | Invalid arguments, invalid selection, or invalid database target. No file ingestion has started. |
| `3` | One or more files were deferred, with no configuration or other ingestion failures. |
| `130` | The process was interrupted by the operator. |

If a command has both deferred files and a configuration or ingestion failure,
it returns `1`. In text mode, result summaries go to standard output and
diagnostics go to standard error. With `--json`, per-file diagnostics are in
the JSON object on standard output; usage errors from argument parsing remain
standard error.

## Acceptance tests

The CLI implementation must test argument validation, empty and invalid
selections, text and JSON output, each outcome, exit-code precedence, mixed
success and failure, and these PostgreSQL paths: new ingestion, completed
replay, interrupted-run resume, per-file lock contention, missing interfaces,
and a batch failure after earlier batches committed. Integration tests must
use migrated development/test databases and unique test records, and must not
target production.

The implementation step that adds the tests will document their exact paths
and commands.
