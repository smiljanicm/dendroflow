# Recovery contract (MVP3a)

## Goal and boundary

An operator must be able to recover DendroFlow's configuration, RAW data,
provenance, and ability to continue ingestion after losing a database host or
application host. This document defines the recoverable state and the checks
for a restore drill. MVP3b will exercise a restore on disposable databases;
MVP3c will record the tested operator commands.

DendroFlow does not currently create backups, schedule them, or manage their
retention. Those are deployment responsibilities. This contract does not
prescribe a scheduler, cloud storage service, or retention interval.

## Assets to preserve

| Asset | Why it matters |
| --- | --- |
| `dendroflow_metadata` PostgreSQL database | Sites, locations, sensors, variables, deployments, and migration history. |
| `dendroflow_raw` PostgreSQL database | File registrations, reader settings, interfaces, file versions, ingestion runs and batches, observations, and migration history. |
| `dendroflow_clean` PostgreSQL database | Any CLEAN datasets and records, plus migration history, even if CLEAN processing is not yet part of the MVP workflow. |
| Source files at registered paths | The databases store paths and fingerprints, not the original file bytes. Growing files must be available for future ingestion. |
| Retained ingestion snapshots | A running or resumable RAW run must be able to read its original, content-addressed snapshot after restart. These files live under `DENDROFLOW_SNAPSHOT_DIR`, not in PostgreSQL. |
| Applied configuration files and operational settings | Keep the reviewed YAML/workbook inputs and the non-secret settings needed to reconstruct file paths, snapshot location, database target, and installed application version. PostgreSQL contains applied state but not necessarily those review artifacts. |
| Database credentials and other secrets | Make these available through the deployment's secret mechanism; do not place plaintext passwords in a portable backup bundle. |

The Compose development setup puts PostgreSQL data in `postgres_data` and
staged snapshots in `dendroflow_snapshots`. Registered source files are outside
those volumes unless the operator has mounted or archived them separately.
Copying only the PostgreSQL volume or only the database dumps does not satisfy
this contract.

## Consistent recovery point

METADATA, RAW, and CLEAN are distinct PostgreSQL databases. A transaction or
`pg_dump` of one database is not an atomic snapshot of all three. For a
coordinated backup, stop new configuration applies, ingestion jobs, migrations,
and other writers, wait for in-flight work to finish, and then capture all
three databases. Preserve the relevant source files and snapshot directory at
the same recovery point before allowing writers to resume. Coordinate any
external process that appends to source files, or take stable, verified file
copies while it runs. Record the time,
application revision or installed package version, database dump identifiers,
and source/snapshot archive identifiers together.

If a writer did not finish cleanly, retain its snapshots and record the
uncertain state; do not infer success or delete resumable snapshots. A combined
configuration apply commits METADATA and RAW separately, so an interrupted
apply may require review of both databases before another plan is applied.
The recovery drill must use a known consistent backup set rather than assume
that independent live dumps form one cross-database transaction.

Backups and required file copies must remain available if the original
database or application storage is lost. Access to them should be restricted
because source data and database dumps may contain sensitive information.

## Restore order

1. Prepare an isolated PostgreSQL target and the matching DendroFlow release.
   Supply credentials separately and confirm the expected target environment.
2. Restore the METADATA, RAW, and CLEAN dumps from one recorded recovery point
   into separate databases. Preserve their IDs and `schema_migrations` rows;
   do not rebuild state by replaying configuration YAML.
3. Restore source files and retained snapshots to their recorded paths, or
   explicitly reconcile any path changes before ingestion. Do not replace a
   resumable run's snapshot with a newer live file.
4. Check schema history, record counts and representative identities, RAW to
   METADATA deployment references, file hashes, and required snapshot hashes.
   Confirm the installed release can read the restored migration history.
5. Only after the checks pass, resume writers. Re-run migrations if the
   installed release has pending migrations, then review any incomplete
   configuration apply or ingestion run before retrying it.

The restore drill must never overwrite the active databases, source files, or
snapshot directory. Production cutover is a separate operator decision after
reviewing the drill evidence.

## Minimum acceptance evidence for MVP3b

- Back up and restore all three databases into uniquely named disposable
  targets. Confirm migration histories and representative records match the
  recorded backup point.
- Confirm that RAW file/interface and observation references still resolve to
  the restored METADATA IDs, and that CLEAN state is present if populated.
- Preserve a representative registered source file and any snapshot needed by
  a resumable run; verify their bytes against the recorded hashes.
- Run the restored release's migration check again without reapplying already
  recorded migrations. Repeat a completed ingestion without introducing
  duplicate RAW observations. Where an interrupted run is included, resume it
  from its retained snapshot rather than the current live source.
- Record the backup identifiers, restore target, version, checks, and any
  limitation in the drill result. Clean up only the disposable targets.

These checks establish recoverability for the tested backup set and release.
They do not establish a backup schedule, retention policy, recovery time
objective, or recovery point objective for a particular lab deployment.
