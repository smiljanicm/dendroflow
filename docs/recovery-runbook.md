# DendroFlow recovery runbook

This runbook implements the [recovery contract](recovery.md). The MVP3b drill
has verified a three-database `pg_dump`/`pg_restore` cycle, restored a source
file and staged snapshot, replayed a completed ingestion, and ingested an
append in disposable PostgreSQL containers. The commands below are templates
for an operator to adapt to the actual file locations and PostgreSQL target;
they have not been exercised against a lab deployment.

## Before a backup

1. Identify the exact PostgreSQL host, port, role, and environment label.
   Check that `psql`, `pg_dump`, and `pg_restore` are available and compatible
   with the server version. Supply database credentials through the
   deployment's secret mechanism. Do not put a password in the backup bundle.
2. Record the DendroFlow Git revision or installed package version, PostgreSQL
   version, backup time, registered source paths, `DENDROFLOW_SNAPSHOT_DIR`,
   and the reviewed YAML/workbook configuration inputs. The `files.filepath`
   values in RAW identify paths that must be recoverable:

   ```bash
   psql -d dendroflow_raw -At -c 'SELECT filepath FROM files ORDER BY file_id'
   ```

3. Pause new configuration applies, ingestion, migrations, CLEAN writers,
   and any other database writers. Let in-flight transactions finish. Also
   coordinate logger writes or capture a stable copy of each growing source.
   Keep writers paused until all three dumps and file copies are complete.
   Three separate live `pg_dump` operations do not form one atomic snapshot
   across databases.

## Capture the backup set

Use an empty, access-restricted directory on storage independent of the
database and application volumes. In these examples, libpq connection
variables `PGHOST`, `PGPORT`, `PGUSER`, and the secret `PGPASSWORD` refer to
the **source** server. Check the connection before dumping:

```bash
psql -d postgres -c 'SELECT current_user, inet_server_addr(), inet_server_port()'
umask 077
backup_dir=/path/to/new-backup-directory
mkdir "$backup_dir"
mkdir "$backup_dir/db"
for db in dendroflow_metadata dendroflow_raw dendroflow_clean; do
  pg_dump --format=custom --no-owner --no-acl \
    --dbname="$db" --file="$backup_dir/db/$db.dump"
done
```

Stop on any command failure. Confirm all three dumps have nonzero size. Keep
the source bytes, staged snapshots, and reviewed configuration along with the
dumps. The following is an example for **one** source directory; repeat it
for every registered path outside that directory. Preserve the original path
layout for restore. Prepare a directory containing only reviewed, non-secret
YAML/workbook inputs and settings; exclude `.env` and credentials.

```bash
source_parent=/path/to/source-parent
source_name=monitoring
snapshot_dir=/absolute/path/to/dendroflow/snapshots
reviewed_config_dir=/path/to/reviewed-config-without-secrets
tar -C "$source_parent" -cf "$backup_dir/source-monitoring.tar" "$source_name"
tar -C "$(dirname "$snapshot_dir")" -cf "$backup_dir/snapshots.tar" \
  "$(basename "$snapshot_dir")"
tar -C "$reviewed_config_dir" -cf "$backup_dir/reviewed-config.tar" .
(cd "$backup_dir" && sha256sum db/*.dump source-monitoring.tar \
  snapshots.tar reviewed-config.tar > SHA256SUMS)
```

Record the source-parent and snapshot paths, every archive name, the dump
checksums, and the application revision in an operator manifest. While writers
are still paused, record the migration versions and counts from the verification
queries below, and hash representative source files and snapshots referenced
by running runs. Check that the bundle can be read from another host. Retain
those snapshots; a newer live file cannot replace them.

## Restore into an isolated target

Never run the restore commands against the active databases. Provision an
isolated PostgreSQL instance with the required role and extensions. Confirm
its host and port independently, then set `PGHOST`, `PGPORT`, `PGUSER`, and
`PGPASSWORD` for **that target**. It must have three empty databases with the
standard names, because the current CLI connects to those names. If the
instance already created them, confirm they are empty; do not drop existing
databases as part of this runbook.

```bash
psql -d postgres -c 'SELECT current_user, inet_server_addr(), inet_server_port()'
(cd "$backup_dir" && sha256sum -c SHA256SUMS)
createdb dendroflow_metadata
createdb dendroflow_raw
createdb dendroflow_clean
for db in dendroflow_metadata dendroflow_raw dendroflow_clean; do
  pg_restore --exit-on-error --no-owner --no-acl \
    --dbname="$db" "$backup_dir/db/$db.dump"
done
```

Run `createdb` only when the target databases do not yet exist. Do not run
application migrations before checking the restored migration history. Restore
file assets on the isolated application host at the recorded paths, with
permissions that allow the DendroFlow process to read them:

```bash
mkdir -p "$source_parent" "$(dirname "$snapshot_dir")"
tar -C "$source_parent" -xf "$backup_dir/source-monitoring.tar"
tar -C "$(dirname "$snapshot_dir")" -xf "$backup_dir/snapshots.tar"
```

Repeat for every source archive. Restore reviewed configuration separately;
recreate database credentials from the secret mechanism. Set the application
`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` to
the same isolated target and set `DENDROFLOW_SNAPSHOT_DIR` to the restored
snapshot location. An environment label such as `recovery-drill` helps name
reports; it does not itself isolate a database connection.

## Verify before resuming writes

Compare the following with the manifest recorded at backup time:

- Migration versions in each `schema_migrations` table, plus counts and
  representative IDs for sites, deployments, files, interfaces, versions,
  ingestion runs, RAW observations, and any populated CLEAN tables.
- RAW interface `deployment_id` values against restored METADATA deployments,
  and CLEAN input `raw_observation_id` values against restored RAW rows.
- Source file paths and content hashes. For any running ingestion run, find its
  file ID and version hash in RAW, then check the staged file at
  `<snapshot_dir>/<file_id>/<sha256-hex>.snapshot` with `sha256sum`. A missing or
  mismatched snapshot blocks resume.

For example, inspect migration versions and representative counts without
writing to the target:

```bash
for db in dendroflow_metadata dendroflow_raw dendroflow_clean; do
  psql -d "$db" -c 'SELECT version FROM schema_migrations ORDER BY version'
done
psql -d dendroflow_metadata -c 'SELECT count(*) FROM deployments'
psql -d dendroflow_raw -c 'SELECT count(*) FROM raw_observations'
psql -d dendroflow_clean -c 'SELECT count(*) FROM clean_observations'
```

With the matching DendroFlow release, `dendroflow migrate` should report no
pending migrations. If the restored backup predates the installed release,
review the pending migrations as a separate upgrade before running them.
For a registered source whose completed version and live bytes are unchanged,
`dendroflow ingest --file-id ID --json` should report `already_completed` and
leave RAW counts unchanged. Do this only on the isolated target, after
checking the source bytes; a grown source legitimately starts another run.

Review incomplete runs individually before retrying. A running run requires
its retained snapshot; if it is unavailable or corrupt, stop and investigate
instead of substituting the current source. For a PARTIAL or UNKNOWN combined
CONFIG apply, inspect both METADATA and RAW state and prepare a new reviewed
plan; do not replay the old YAML blindly.

Record the restore target, release, archive checksums, comparison results,
ingestion outcomes, and any failed checks. A failed check blocks cutover.
Removing the disposable target and selecting a production cutover procedure
are separate operator decisions. This runbook does not set a backup schedule,
retention policy, or recovery time objective.
