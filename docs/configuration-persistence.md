# Configuration persistence

This document describes METADATA and RAW configuration persistence,
including writers, preparation, execution ordering, and public
transaction-owning apply functions.

METADATA-only plans can use `apply_metadata_plan()`.
RAW-only plans can use `apply_raw_plan()`.
`apply_plan()` supports combined plans and either stage on its own,
with explicit execution-failure outcomes.

Combined apply uses sequential METADATA and RAW transactions.
It does not provide atomicity across the two databases.

## Planning and persistence

Configuration planning interprets user intent, resolves selectors and
aliases, determines CREATE / REUSE / UPDATE actions, and records changes.

Persistence executes resolved operations. It does not search natural
keys, reinterpret aliases, choose an action, or decide whether an
identity correction is appropriate.

An UPDATE represents corrected metadata for the same resource and
preserves its database ID.

## Supported METADATA resources

| Resource | Table | Primary key | CREATE | UPDATE |
| --- | --- | --- | --- | --- |
| site | sites | site_id | Yes | Yes |
| location_type | location_types | location_type_id | Yes | Yes |
| sensor_type | sensor_types | sensor_type_id | Yes | Yes |
| variable | variables | variable_id | Yes | Yes |
| sensor_model | sensor_models | sensor_model_id | Yes | Yes |
| sensor | sensors | sensor_id | Yes | Yes |
| location | locations | location_id | Yes | Yes |
| location_label | location_labels | location_label_id | Yes | No |
| deployment | deployments | deployment_id | Yes | Yes |

Files and interfaces are RAW resources and are not accepted by these
METADATA writers.

REUSE is not an INSERT or UPDATE. Neither writer accepts REUSE items.

## CREATE contract

`create_metadata_item(connection, item, context)` accepts a resolved
CREATE item for a supported resource.

The writer:

1. Checks the action, resource type, and resolved-values class.
2. Resolves required relationships through `ApplyContext`.
3. Executes one INSERT with a RETURNING clause.
4. Retrieves the generated database ID.
5. Registers the plan ID, resource type, and database ID in the context.
6. Returns an `ApplyItemResult`.

CREATE does not perform an upsert or rediscover an existing resource.
Database errors propagate to the caller.

Context registration and a returned result do not mean the transaction
has committed. Transaction and context lifecycle management belong to
the caller.

## UPDATE fields

Scalar fields map to database columns with the same names.
Relationship mappings are listed explicitly below.

| Resource | Scalar fields | Relationship mappings |
| --- | --- | --- |
| site | name, site_code, description, latitude, longitude | parent → parent_id |
| location_type | type, description | None |
| sensor_type | type, description | None |
| variable | variable, derived, description | None |
| sensor_model | manufacturer, model | sensor_type → sensor_type_id |
| sensor | serial_number, description | sensor_model → sensor_model_id |
| location | latitude, longitude, height_above_ground, azimuth | site → site_id; location_type → location_type_id |
| deployment | valid_from, valid_to | sensor → sensor_id; location → location_id; variable → variable_id |

This table describes writer capabilities, not the YAML schema.
For example, the site writer supports `parent`, but the current YAML
site-update model does not expose that field.

A location UPDATE does not modify location labels. The location's
planning identity is not an additional writable database column.

## UPDATE validation

`update_metadata_item(connection, item, context)` requires:

- UPDATE action.
- A supported resource and its matching resolved-values class.
- A positive integer database ID; booleans are not accepted.
- At least one change.
- Supported, non-duplicate change fields.
- Each `change.after` to match the corresponding resolved value.

The plan-item model rejects missing UPDATE IDs and empty change lists.
The writer validates its remaining input contract before SQL.

These checks do not replace configuration validation, plan consistency
checks, or database constraints.

## Guarded UPDATE execution

Only fields listed in `item.changes` appear in assignments and guards.

For every changed field, the writer prepares:

- Its database column.
- Its resolved final value.
- Its recorded previous value.

One UPDATE statement targets the primary key and checks each previous
value with `IS NOT DISTINCT FROM`. This comparison also handles NULL.

The statement returns the existing primary key. A successful result
must contain exactly that integer ID.

Unchanged fields are neither written nor guarded. Consequently,
concurrent changes to unchanged fields do not by themselves make the
UPDATE stale.

A single guarded statement does not provide atomicity for an entire
multi-item plan.

## Relationship and timestamp handling

`ApplyContext` resolves:

- `ExistingRef` directly to its database ID.
- `PlannedRef` through a previously registered plan ID with a matching
  resource type.

An unavailable or mismatched planned registration raises
`UNRESOLVED_PLANNED_REF`.

For changed relationships, both assignment and guard references are
resolved before SQL. All changes are prepared before the statement
executes, so a later reference-resolution failure causes no SQL call.

UPDATE writers do not register new resource IDs.

Deployment timestamps are passed unchanged to the database driver.
The writer does not normalize timezones or reconstruct datetime values.
Clearing `valid_to` passes `None`.

This pass-through contract does not describe PostgreSQL's timestamp
storage or display behavior.

## Results and failures

A successful writer returns an `ApplyItemResult` containing the plan ID,
resource type, action, and database ID.

For UPDATE:

- No returned row raises `ApplyError` with code `STALE_PLAN`.
- A malformed returned row or unexpected ID raises `ValueError`.
- Exceptions from execution or result retrieval propagate unchanged.

A stale result can mean that the target row disappeared or that a
guarded value changed. The writer does not distinguish those causes.

There is no automatic retry. A stale plan requires re-planning, review,
and another apply attempt.

## Confirmation and transactions

`validate_plan_for_apply()` rejects plans containing errors and requires
explicit confirmation when the plan marks changes as requiring it.

Individual writers do not call this preflight function themselves.
The apply layer must run it before writes.

Writers do not commit, roll back, manage transaction boundaries, or
schedule dependent operations. The caller must provide the intended
transaction context and handle failures.

## Deployment constraints

PostgreSQL requires `valid_to > valid_from` when an end is present.
It also prevents overlapping deployment intervals for the same sensor
and variable, regardless of location.

Intervals are half-open: an interval may end exactly when the next
begins.

The database remains authoritative if concurrent changes invalidate a
previously checked plan.

Deployment UPDATE resolution rejects final intervals whose end is not
later than their start.

Overlap checks compare final CREATE and UPDATE values against each
other and against unchanged persisted deployments. Persisted snapshots
of deployments updated by the plan are excluded from the existing-history
check because their final values are checked in the planned-state check.

METADATA preparation accounts for immediate database constraints,
including plans that close an old deployment and create its successor.
The dependency rules are described below.

## Verification boundary

Unit tests cover SQL construction, parameter ordering, reference
resolution, input validation, returned results, stale-plan handling,
and exception propagation.

Fake-connection tests do not establish real PostgreSQL constraint
behavior, concurrency behavior, or whole-plan rollback guarantees.
Those require database integration tests.

## METADATA apply preparation and ordering

`prepare_metadata_plan()` checks the METADATA-only apply boundary
without opening a database connection.

It runs apply preflight, rejects RAW items, validates supported
resource/action/value combinations, checks existing resource IDs,
and rejects duplicate plan IDs and duplicate UPDATE targets.

Relationship checks require each planned reference to target a
matching METADATA CREATE item. REUSE relationships must refer to
existing resources.

The returned `MetadataPreparation` contains:

- `items`: the original plan order.
- `execution_items`: the order determined by dependencies.
- `requires_writes`: whether CREATE or UPDATE items are present.

Preparation does not execute SQL or report a committed apply result.

### Dependency rules

The execution graph combines three kinds of dependency:

1. A CREATE precedes an operation that requires its generated ID.
2. An UPDATE releasing a unique key precedes an operation acquiring
   that previous key.
3. A deployment UPDATE precedes another operation whose final state
   overlaps its previous sensor, variable, and interval.

Previous constraint values are reconstructed from resolved final values
and recorded `FieldChange.before` values.

Unique-key dependencies cover site codes, location types, sensor types,
variables, manufacturer/model pairs, and sensor-model/serial-number
pairs. Composite comparisons include unchanged key components.

Deployment comparisons use sensor and variable, regardless of location.
Intervals are half-open, so adjacent boundaries do not overlap.
Overlapping final CREATE/UPDATE deployment states are rejected.

REUSE items do not acquire or release constraint values. An updated
row's REUSE snapshot therefore does not override its final UPDATE state.

### Deterministic order and cycles

At each step, ordering selects the earliest original item whose
dependencies have been satisfied.

Reference and constraint dependencies are combined before ordering.
A dependency cycle raises `PLAN_NOT_APPLICABLE` and identifies blocked
items. The blocked list can include dependants of the cycle.

The scheduler does not split UPDATE statements, introduce temporary
values, or defer database constraints to resolve cycles.

Original item order remains available separately for result reporting.

### Guarantees and limits

Preparation uses the resolved plan and performs no database lookups.
It does not replace resolution, writer validation, or PostgreSQL
constraints.

Concurrent database changes can still invalidate a prepared schedule.
Database failures and stale UPDATE guards remain authoritative during
execution.

Unit tests establish dependency construction, ordering, and rejection
behavior. The execution layer consumes this schedule, and the public
apply function owns the connection and transaction described below.

## Public METADATA apply

```python
from dendroflow.configuration.persistence import apply_metadata_plan

result = apply_metadata_plan(
    plan,
    confirm_identity_changes=False,
)
```

`apply_metadata_plan()` accepts a METADATA-only resolved plan.
Preparation and confirmation checks complete before connecting.
Plans containing RAW items are rejected.

Each call creates a fresh `ApplyContext`. Plans containing CREATE or
UPDATE operations use a dedicated `dendroflow_metadata` connection.
All scheduled writes execute within that connection's transaction.

The function returns SUCCESS with METADATA COMMITTED only after the
connection context exits successfully. RAW is NOT_REQUIRED.
Item results follow original plan order, regardless of execution order.

Empty and REUSE-only plans do not open a database connection.
They return SUCCESS with both stages NOT_REQUIRED. REUSE results
contain the supplied existing IDs; they do not verify current database
state.

Preparation, connection, execution, and commit errors propagate.
Execution errors leave the connection context exceptionally, causing
transaction rollback. The function does not return a failure result
or retry automatically.

A commit error can leave the outcome uncertain, for example if the
connection is lost during commit. Callers must establish database state
before deciding whether another apply attempt is appropriate.

The internal `execute_metadata_preparation()` function does not own
transactions. Its returned item results describe executed operations,
not committed changes.

## METADATA PostgreSQL integration verification

The integration tests use the public apply function and inspect
database state through separate connections.

They cover:

- Committed CREATE, UPDATE, and REUSE results.
- Parent creation before a dependent child.
- Original-order result reporting.
- Unique site-code release before acquisition.
- Rollback of earlier INSERT and UPDATE operations after a stale guard.
- Rollback after PostgreSQL unique and check violations.

Tests use unique site codes and clean up their fixture rows.
They require a local development METADATA database with migrations
applied and the normal DendroFlow connection settings configured.

Run explicitly:

```bash
DENDROFLOW_INTEGRATION=1 pytest -q \
  tests/integration/test_configuration_apply.py
```

Without that environment variable, these tests are skipped.

These cases verify representative METADATA transaction behavior.
They do not establish concurrent-execution guarantees, uncertain
commit recovery, deployment exclusion-constraint behavior, or
cross-database atomicity.

## RAW configuration persistence

RAW configuration persistence supports these resources:

| Resource | Table | Primary key | Supported actions |
| --- | --- | --- | --- |
| file | files | file_id | CREATE, REUSE |
| interface | sensor_file_interfaces | interface_id | CREATE, REUSE |

RAW UPDATE is not supported. Conflicting existing configuration is
reported during resolution rather than silently overwritten.

### Writers

`create_raw_item(connection, item, context)` persists one CREATE item.

File creation stores the supplied filepath, timestamp timezone,
timestamp format, and reader configuration. The top-level reader
mapping is copied to a dictionary and adapted to JSONB; nested values
must be JSON-serializable.

Interface creation resolves file and deployment references before
executing SQL. Both references must have the expected resource type.

Each writer executes one INSERT with RETURNING, validates the generated
ID, registers it in the context, and returns an `ApplyItemResult`.
Writers do not connect, commit, roll back, or retry.

A duplicate filepath or duplicate `(file_id, values_column)` remains
a database error. CREATE does not become REUSE automatically.

### Preparation and execution

`prepare_raw_plan()` runs preflight checks without database access.
It validates supported actions, values classes, IDs, unique plan IDs,
and relationship references.

New files execute before interfaces that reference them. Ordering
selects the earliest original item whose dependencies are ready.
Results retain original RAW plan order.

REUSE items perform no SQL and cannot depend on planned resources.
Their supplied IDs are not revalidated against current database state.

By default, preparation rejects METADATA items and planned deployment
references.

Internal combined preparation can explicitly enable METADATA
dependencies. Planned deployments must target matching METADATA CREATE
items. Their plan IDs are recorded in `required_metadata_plan_ids`.

`execute_raw_preparation()` checks all required deployment registrations
before any RAW writes. It executes CREATE items and produces REUSE
results without managing transactions.

A registration does not prove that METADATA committed. The combined
orchestrator must supply IDs from committed METADATA work and validate
the METADATA stage separately.

### Public RAW apply

```python
from dendroflow.configuration.persistence import apply_raw_plan

result = apply_raw_plan(plan)
```

`apply_raw_plan()` accepts RAW-only CREATE/REUSE plans.
Interfaces may reference files created in the same plan, but deployment
references must be existing references. METADATA items are rejected.

Preparation completes before connecting. Each call uses a fresh
context. Plans requiring writes use one owned `dendroflow_raw`
transaction.

Successful write plans return SUCCESS, RAW COMMITTED, and METADATA
NOT_REQUIRED only after the connection context exits successfully.

Empty and REUSE-only plans do not connect. They return SUCCESS with
both stages NOT_REQUIRED.

Errors propagate without automatic retries. Execution failures roll
back the RAW transaction. A commit error may leave its outcome uncertain;
callers must establish database state before deciding on another attempt.

### Configuration and ingestion boundary

Registration does not read the physical file or require it to exist.
It does not create file versions, ingestion runs, or observations.

A new filepath can be registered as a new file. Changed contents at an
existing filepath are handled by ingestion's file-version tracking.
Changed reader settings remain configuration conflicts until a RAW
UPDATE contract is introduced.

RAW enforces its file foreign key. It has no cross-database foreign key
for deployment IDs, and RAW apply does not query METADATA to verify
existing deployments. Resolution supplies those references; concurrent
METADATA changes are not prevented by the RAW transaction.

### RAW PostgreSQL integration verification

The integration tests cover:

- Committed file and interface rows with original-order results.
- JSONB reader-configuration round-trip.
- Reading an actual CSV through the stored ingestion configuration.
- Adding an interface while reusing existing configuration.
- Rollback after duplicate filepath and interface errors.
- Rollback after a file foreign-key violation.

Tests create a committed METADATA deployment fixture, inspect RAW state
through separate connections, and clean up their own rows. RAW cleanup
precedes METADATA cleanup.

Run against local development databases with METADATA and RAW migrations
applied and normal DendroFlow connection settings configured:

```bash
DENDROFLOW_INTEGRATION=1 pytest -q \
  tests/integration/test_configuration_raw_apply.py
```

Without the opt-in environment variable, these tests are skipped.

These tests do not establish cross-database atomicity, concurrent-change
protection, or recovery from an uncertain commit outcome.

## Public combined apply

```python
from dendroflow.configuration.persistence import apply_plan

result = apply_plan(
    plan,
    confirm_identity_changes=False,
)
```

`apply_plan()` accepts combined, METADATA-only, RAW-only, empty, and
REUSE-only resolved plans.

Both stages are prepared before any database connection is opened.
Preparation checks confirmation requirements, supported operations,
plan-ID uniqueness, references, and execution dependencies.

Preparation failures propagate directly. They do not produce an
`ApplyExecutionError`, and no writes have started.

### Execution sequence

When writes are required:

1. METADATA executes on an owned `dendroflow_metadata` connection.
2. METADATA commit must return successfully before RAW can proceed.
3. Required newly created deployment IDs are transferred from committed
   METADATA results into a fresh RAW context.
4. RAW executes on an owned `dendroflow_raw` connection and commits
   separately.

Each stage uses a fresh context. Uncommitted or uncertain METADATA
results are never used to start dependent RAW writes.

If METADATA fails to finish cleanly, RAW writes do not start. This
includes a connection-close failure after METADATA commit succeeded.

Stages containing only REUSE items require no connection or transaction.
Their supplied IDs are returned without checking current database state.

Results retain original plan order: METADATA items followed by RAW
items. Execution order may differ because of dependencies.

### Stage outcomes

| Stage status | Meaning |
| --- | --- |
| NOT_REQUIRED | The stage requires no write transaction; it may contain completed REUSE operations. |
| NOT_STARTED | Required writes were not attempted because the preceding stage did not finish cleanly. |
| COMMITTED | Commit returned successfully, even if subsequent connection cleanup failed. |
| FAILED | Connection failed before execution, or execution failed and rollback completed successfully. |
| UNKNOWN | Commit raised an error, or rollback failed; the transaction outcome is uncertain. |

A commit error remains UNKNOWN even if a subsequent rollback succeeds.
That rollback cannot establish whether the earlier commit took effect.

### Overall outcomes

| Overall status | Meaning |
| --- | --- |
| SUCCESS | Every required write stage committed; stages without writes completed without a transaction. |
| FAILED | A required stage failed without an earlier committed write stage. |
| PARTIAL | METADATA committed, but required RAW writes failed or were not started. |
| UNKNOWN | At least one stage has an uncertain transaction outcome. |

UNKNOWN takes precedence over PARTIAL. For example, committed METADATA
followed by an uncertain RAW commit produces UNKNOWN.

Result items include only acknowledged committed stage results and
completed REUSE operations. Items from failed, unstarted, or uncertain
write stages are excluded.

A stage that requires writes reports none of its item results if that
transaction fails or becomes uncertain, including REUSE items within
that stage.

### Execution errors and cleanup

Ordinary connection, execution, commit, rollback, and close failures
raise `ApplyExecutionError`. Its `result` describes the known database
outcome.

```python
from dendroflow.configuration.persistence import (
    ApplyExecutionError,
    apply_plan,
)

try:
    result = apply_plan(plan)
except ApplyExecutionError as error:
    outcome = error.result
    # Record outcome.status, both stage statuses, and outcome.items.
    # Inspect database state before deciding how to recover.
    raise
```

Exception chaining retains the underlying failure. The internal stage
error also retains rollback and connection-close errors separately.

An exception does not imply that writes rolled back. If commit
succeeded and connection close then failed, the stage remains COMMITTED.
An `ApplyExecutionError` can therefore carry an overall SUCCESS result
when all required work committed before cleanup failed.

Process-control exceptions, such as KeyboardInterrupt and SystemExit,
propagate directly rather than being converted into structured apply
outcomes.

The standalone `apply_metadata_plan()` and `apply_raw_plan()` functions
retain their existing exception behavior. They do not provide the
combined function's structured execution-failure contract.

### Recovery boundaries

There is no cross-database transaction, automatic compensation, or
automatic retry.

If RAW fails after METADATA committed, METADATA remains persisted.
Recovery requires inspecting the outcome and current database state,
then resolving and reviewing a new plan.

Do not replay the original CREATE plan blindly: previously committed
resources may now need REUSE operations.

For UNKNOWN outcomes, establish database state before deciding what to
apply next. Missing item results do not prove that uncertain writes
were rolled back.

For SUCCESS accompanied by a cleanup error, committed work must not
be repeated solely because an exception was raised.

## Combined PostgreSQL integration verification

The combined integration tests inspect persisted state through separate
connections and cover:

- Successful METADATA and RAW commits.
- Dependency ordering and original-order result reporting.
- Transfer of a newly committed deployment ID into a RAW interface.
- Invalid RAW preparation preventing both stages from starting.
- METADATA unique-constraint failure rolling back METADATA and preventing
  RAW execution.
- Duplicate RAW file and interface failures rolling back RAW while
  preserving committed METADATA and reporting PARTIAL.

Fixtures use unique identifiers and clean up RAW before METADATA.

Run all three configuration apply integration modules against local
development databases with migrations and connection settings prepared:

```bash
DENDROFLOW_INTEGRATION=1 pytest -q \
  tests/integration/test_configuration_apply.py \
  tests/integration/test_configuration_raw_apply.py \
  tests/integration/test_configuration_combined_apply.py
```

Without the opt-in environment variable, these tests are skipped.

Unit tests exercise uncertain commit, rollback, and cleanup outcomes
using controlled connection failures. The PostgreSQL integration cases
do not establish network-failure recovery, concurrent-execution
guarantees, or cross-database atomicity.

## Phase E scope and deferred work

Phase E implements the persistence boundary for resolved configuration
plans:

- METADATA CREATE and supported guarded UPDATE operations.
- RAW file and interface CREATE operations.
- REUSE results without writes.
- Preparation, validation, and dependency ordering.
- Standalone METADATA and RAW apply entry points.
- Combined METADATA-before-RAW apply with explicit transaction outcomes.
- Unit tests and opt-in PostgreSQL integration tests.

Phase E persistence is complete. The subsequent YAML CLI and workbook
workflow have also completed CONFIG MVP acceptance; see the
[acceptance record](configuration-workbook.md#acceptance-record-2026-09-25).
The transaction and recovery limitations documented above remain unchanged.

### Future RAW UPDATE work

RAW UPDATE is deferred beyond the CONFIG MVP. Existing RAW files and
interfaces continue to support CREATE and REUSE only; conflicting settings
are rejected. Future UPDATE support requires a separate design and acceptance
phase.

The future-work list includes:

- Changing a filepath while preserving file_id and its associated
  provenance history.
- Changing reader configuration or timestamp settings, including the
  effect on interpretation and re-ingestion of existing data.
- Updating interfaces, including column mappings, units, and deployment
  associations, with explicit provenance rules.
- Defining identity, confirmation, stale-plan protection, and recovery
  behavior for these updates.

Registering a new filepath currently creates a separate file resource.
It does not rename an existing registration or transfer its history.
