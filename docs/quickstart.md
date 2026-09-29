# Fresh-clone quickstart

This is a first-user exercise from `git clone` through an appended file. It
uses one small synthetic CSV and a **new, empty** local PostgreSQL volume. Run
the DendroFlow CLI in a host virtual environment; Docker Compose supplies
PostgreSQL only. The application container does not mount the example source
directory. This is an interactive local walkthrough, not a lab deployment or
an automated backup procedure.

## Requirements and target

- Git, Python 3.10 or later with `venv` and `pip`, and Docker with Compose.
- An available local PostgreSQL port (this walkthrough uses `55432`).
- Permission to create files under the cloned repository and enough free space
  to retain more than one full copy of the CSV in `.demo/snapshots`.

Use a separate terminal and clone directory on the same machine. This
walkthrough has its own Compose file, project name, port, and PostgreSQL
volume, so an existing DendroFlow stack can keep running. A second directory
alone does not isolate Docker resources. The steps assume an empty quickstart
volume; do not use `ingest --all` against a database containing other
registered files.

## 1. Clone, install, and start PostgreSQL

Run these from a shell on the host:

```bash
git clone https://github.com/smiljanicm/dendroflow.git
cd dendroflow
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

Edit this clone's `.env`: replace `POSTGRES_PASSWORD=change-me` with a
password for this local instance, and set `POSTGRES_PORT=55432` (choose another
unused port if necessary). `.env` is not committed to Git. Start the dedicated
quickstart database from the clone root:

```bash
docker compose --env-file .env -f examples/quickstart/compose.yaml \
  -p dendroflow-quickstart up -d postgres
docker compose --env-file .env -f examples/quickstart/compose.yaml \
  -p dendroflow-quickstart ps postgres
dendroflow migrate
```

Wait until the PostgreSQL service is healthy before migrating. The migration
command should apply versions to METADATA, RAW, and CLEAN; a second invocation
should report `No pending migrations` for all three. If the Docker volume
already contains databases, this is not a fresh-clone acceptance run. Your
host CLI reads this clone's `.env`; if you have exported `POSTGRES_HOST`,
`POSTGRES_PORT`, `POSTGRES_USER`, or `POSTGRES_PASSWORD` in this terminal,
unset them first so they cannot override the quickstart connection settings.

## 2. Prepare the example source and snapshots

Keep the shell in the repository root. The example CONFIG file uses the
relative path `.demo/logger.csv`; running later commands from another working
directory would resolve that path differently. Production registrations should
use absolute paths visible to the process doing ingestion.

```bash
mkdir -p .demo/snapshots
cp examples/quickstart/logger.csv .demo/logger.csv
export DENDROFLOW_SNAPSHOT_DIR="$PWD/.demo/snapshots"
dendroflow discover --root .demo --include '*.csv' --json
```

The first discovery should show `logger.csv` as `unregistered`. Its exit code
is `1` because it found a file needing configuration; that is the intended
result at this step. Discovery reads paths only and does not register the file.

## 3. Review and apply configuration

Read `examples/quickstart/config.yaml`. It defines a site, one location and
sensor, a variable, a deployment, and one interface mapping the CSV `value`
column to that deployment. The logger timestamps are interpreted as UTC; the
values use `cm` as the example unit.

```bash
dendroflow config validate examples/quickstart/config.yaml
dendroflow config plan examples/quickstart/config.yaml
dendroflow config apply examples/quickstart/config.yaml --yes
dendroflow discover --root .demo --include '*.csv' --json
```

Review the plan before applying. The second discovery should classify the
file as `registered` and show its file ID. CONFIG registers the source and its
meaning but does not ingest measurements.

## 4. Ingest, replay, and append

On this clean example database, `--all` selects just the one registered file:

```bash
dendroflow ingest --all --json
dendroflow ingest --all --json
cat >> .demo/logger.csv <<'CSV'
2026-01-02 00:30:00,10.2
CSV
dendroflow ingest --all --json
dendroflow ingest --all --json
```

Expected outcomes in order:

| Run | Outcome | Observation effect |
| --- | --- | --- |
| First | `completed` | Two observations inserted. |
| Unchanged replay | `already_completed` | No new observations. |
| After append | `completed` | One new observation inserted; the original two retain their provenance. |
| Final replay | `already_completed` | No new observations. |

The appended physical record must end with a newline. DendroFlow captures a
stable snapshot of the **whole** file each time; it does not copy only the new
bytes. It normally waits for the source to remain stable for one second.
Inspect the JSON run ID, file-version ID, snapshot hash, and counts after each
invocation. A new complete row produces a new version and run; older matching
rows are counted as unchanged in that invocation.

## Next step and limits

Keep `.demo/` and the Compose volume while inspecting results; `.demo/` is
ignored by Git. To stop only this quickstart database without deleting its
volume, run:

```bash
docker compose --env-file .env -f examples/quickstart/compose.yaml \
  -p dendroflow-quickstart down
```

The example path and metadata are only for this clean
walkthrough. Once it works, repeat the same workflow with a **copy** of one
representative lab file and its actual timezone, parser settings, deployment,
columns, and units. The [recovery runbook](recovery-runbook.md) covers backup
and restore separately. Note any command that required undocumented choices
or produced surprising output; those are the onboarding issues this prototype
is meant to reveal.
