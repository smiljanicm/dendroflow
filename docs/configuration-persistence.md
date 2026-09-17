# Configuration persistence

This document describes METADATA CREATE and UPDATE writers, preparation,
execution ordering, and the public transaction-owning apply function.

METADATA-only plans can be applied through `apply_metadata_plan()`.
RAW persistence and combined METADATA/RAW orchestration remain separate
work.

## Planning and persistence

Configuration planning interprets user intent, resolves selectors and
aliases, determines CREATE / REUSE / UPDATE actions, and records changes.

Persistence executes resolved operations. It does not search natural
keys, reinterpret aliases, choose an action, or decide whether an
identity correction is appropriate.

An UPDATE represents corrected metadata for the same resource and
preserves its database ID.

## Supported resources

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

## Deployment constraints and remaining work

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

Execution ordering must also account for immediate database constraints,
including plans that close an old deployment and create its successor.

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

## PostgreSQL integration verification

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
