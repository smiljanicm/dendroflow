# Configuration CLI

The CONFIG commands validate YAML, preview database changes, and apply the
reviewed plan. They register metadata and RAW file/interface definitions;
they do not ingest measurements.

## Setup

From the repository, with your virtual environment activated:

```bash
python -m pip install -e ".[dev]"
dendroflow --help
dendroflow config --help
```

`python -m dendroflow` provides the same commands as `dendroflow`.

Configure the local database connection and apply the required
[database migrations](database-migrations.md) before planning or applying:

```bash
dendroflow migrate
```

Validation does not require a database connection. Planning and applying
require the configured METADATA and RAW databases.

## Validate, preview, apply

For a small example, save this as `config.yaml`, choosing a site code
appropriate for your database:

```yaml
sites:
  - site_code: example_site
    name: Example monitoring site
```

Then run:

```bash
dendroflow config validate config.yaml
dendroflow config plan config.yaml
dendroflow config apply config.yaml
```

- `validate` checks YAML parsing, model constraints, and configuration-level
  consistency. Success explicitly states that database state was not checked.
- `plan` resolves current database resources, reports CREATE/REUSE/UPDATE
  operations and diagnostics, and checks preparation and dependency constraints.
  It writes nothing.
- `apply` resolves a fresh plan, prints it, checks applicability and confirmation,
  and executes that same reviewed plan. It does not resolve a different plan
  after confirmation.

A separate `plan` invocation is a preview, not a reservation or a saved executable
plan. Database changes between preview and apply can change the next plan.
Concurrent changes during an apply can also cause execution to fail.

The report includes source paths, values, references, update changes, and any
confirmation requirement. Report order is not a promise of SQL execution order;
persistence orders operations to satisfy dependencies and constraints.

## Confirmation

For an interactive apply that requires writes, answer `y` or `yes` to the prompt.
An empty response, another response, or end-of-input cancels the apply.

For non-interactive execution:

```bash
dendroflow config apply config.yaml --yes
```

Identity-changing updates need separate, explicit authorization:

```bash
dendroflow config apply config.yaml --yes --confirm-identity-changes
```

`--yes` approves execution but does not authorize identity changes.
`--confirm-identity-changes` authorizes those changes but does not replace
execution approval. Neither flag bypasses conflicts or preparation checks.

A plan containing only REUSE operations needs no write confirmation and reports
its stages as NOT_REQUIRED.

## Workbook workflow

For spreadsheet-based configuration work, export a workbook, validate it,
convert its changes to YAML, review the resulting CONFIG plan, and apply it:

```bash
dendroflow config workbook export --site-id 2 control.xlsx
dendroflow config workbook validate control.xlsx
dendroflow config workbook convert control.xlsx desired-config.yaml
dendroflow config plan desired-config.yaml
dendroflow config apply desired-config.yaml
```

The workbook's environment label must match the configured target environment.
Export and conversion compare against current database state; conversion writes
YAML only after verifying the resolved CONFIG plan. Review the YAML and plan
before applying. See [Configuration workbook workflow](configuration-workbook.md)
for workbook scope, supported changes, diagnostics, and detailed examples.

## Declarations and explicit updates

A declaration requests creation or compatible reuse. Changing a declaration's
values does not silently update an existing resource; differences can produce
CONFLICT diagnostics.

To change an existing site's name, use an explicit update in a separate
configuration such as:

```yaml
updates:
  sites:
    - update:
        site_code: example_site
      set:
        name: Revised monitoring site
```

Preview and apply it using the same commands. An identity change, such as changing
`site_code`, additionally requires `--confirm-identity-changes`.

METADATA supports CREATE, REUSE, and the documented UPDATE operations.
RAW files and interfaces currently support CREATE and REUSE only.
RAW updates, including changing a registered filepath while preserving its
history, are deferred beyond the CONFIG MVP.

File registration does not require the source file to exist and does not read
its measurements. Ingestion is a separate workflow. Existing sample
configurations can conflict with previously seeded records; adjust your input
to the intended database state rather than treating every conflict as a CLI
failure.

## Exit codes and diagnostics

| Code | Meaning |
| --- | --- |
| 0 | Command completed successfully, including an apply with no writes required. |
| 1 | Planning/database execution failure, or an execution/cleanup error without a PARTIAL or UNKNOWN outcome. |
| 2 | Invalid input or arguments, plan conflicts, or failed applicability/preparation checks. |
| 3 | Required confirmation missing or execution declined. |
| 4 | Apply reported PARTIAL completion. |
| 5 | Apply reported UNKNOWN database outcome. |

Normal reports and apply outcomes go to stdout. Failure diagnostics go to stderr.
To inspect the exit code in a shell, run `echo $?` immediately after the command.
Help exits successfully. Process interruptions are not mapped to this table.

## Outcomes and recovery

METADATA and RAW use separate transactions. METADATA runs first; RAW runs only
after the preceding stage completes successfully. There is no atomic transaction
covering both databases.

- SUCCESS means the database work completed. A later connection-close failure
  can still produce exit code 1; inspect the reported stage outcomes before
  considering another apply.
- FAILED means no write stage is reported committed. Fix the reported problem
  and preview a fresh plan. A stale update requires a fresh review of current
  database values.
- PARTIAL means a stage committed while subsequent work failed or could not
  proceed. Inspect both databases and the diagnostics before preparing a
  recovery plan.
- UNKNOWN means the client cannot determine the database outcome, for example
  after an ambiguous commit failure. Verify actual database state before
  retrying. A rollback attempt does not establish that an earlier commit failed.

Reported items describe acknowledged operations; a failed stage may have attempted
other statements that were rolled back. Reports are not a complete SQL audit log.
There is no automatic retry or automatic cross-database compensation.

See [configuration persistence](configuration-persistence.md) for stage statuses,
transaction ownership, and the public Python apply APIs.

## Verification

CLI unit tests run without PostgreSQL:

```bash
pytest -q tests/test_cli*.py
```

The CLI integration tests use unique records and remove their own records after
each test. Use configured, migrated development/test databases:

```bash
DENDROFLOW_INTEGRATION=1 pytest -q \
  tests/integration/test_configuration_cli.py \
  tests/integration/test_configuration_apply.py \
  tests/integration/test_configuration_raw_apply.py \
  tests/integration/test_configuration_combined_apply.py
```

The CLI integration module covers the module entry point, YAML workflow, and
workbook acceptance cases for unchanged round trips, supported updates and
additions, interfaces on existing files, and rejection of unsupported edits. It
also tests repeat apply, identity confirmation, conflict rejection, declined
execution, stale-update rollback, and partial completion after a concurrent RAW
insertion. Race tests insert controlled database changes after review to make
these cases deterministic. Uncertain commit and cleanup failures remain covered
by unit tests.

Integration tests skip by default when `DENDROFLOW_INTEGRATION` is not `1`.
JSON output, saved executable plans, and an interactive configuration wizard
are optional work after MVP.

## CONFIG MVP status

The YAML and workbook CONFIG workflows completed acceptance on 2026-09-25.
The full suite with PostgreSQL integration enabled reported 1794 passing tests.
The local workbook check verified an unchanged plan, a single description
update, successful apply, and a no-op repeat plan. See the
[acceptance record](configuration-workbook.md#acceptance-record-2026-09-25)
for the checks and their scope. RAW UPDATE remains deferred beyond this MVP;
file registration and measurement ingestion remain separate operations.
