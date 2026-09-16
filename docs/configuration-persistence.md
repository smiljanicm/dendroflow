# Configuration persistence

This document describes the implemented METADATA CREATE and UPDATE
writers and their boundary with configuration planning.

Whole-plan apply orchestration, transaction management, and RAW
persistence are separate work. The individual writers do not constitute
a complete configuration-apply workflow.

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

Before whole-plan apply orchestration, deployment planning needs
follow-up work to:

- Reject invalid final UPDATE intervals during planning.
- Compare against other updates' final states when checking existing
  deployment overlaps.

Execution ordering must also account for immediate database constraints,
including plans that close an old deployment and create its successor.

## Verification boundary

Unit tests cover SQL construction, parameter ordering, reference
resolution, input validation, returned results, stale-plan handling,
and exception propagation.

Fake-connection tests do not establish real PostgreSQL constraint
behavior, concurrency behavior, or whole-plan rollback guarantees.
Those require database integration tests.