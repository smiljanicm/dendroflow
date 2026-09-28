# Database Migrations

## Purpose

DendroFlow uses version-controlled database migrations to create and evolve its PostgreSQL database schemas.

Migrations provide a reproducible history of database structure changes and ensure that schema changes are explicit, reviewable, and tracked in Git.

The data model and architectural rationale are documented separately in `docs/data-architecture.md`. Migration files implement that architecture.

---

## Database Structure

DendroFlow uses three separate PostgreSQL databases:

```text
dendroflow_metadata
dendroflow_raw
dendroflow_clean
```

Each database has its own migration history:

```text
db/
├── metadata/
│   └── migrations/
│       └── 001_initial.sql
├── raw/
│   └── migrations/
│       └── 001_initial.sql
└── clean/
    └── migrations/
        └── 001_initial.sql
```

Keeping migration histories separate reflects the intentional separation of responsibilities between the three databases.

---

## Migration Approach

DendroFlow currently uses plain SQL migration files.

Each migration represents a **coherent schema change**, rather than an individual table.

For example:

```text
001_initial.sql
002_add_location_labels.sql
003_add_ingestion_metadata.sql
```

A migration may create or modify multiple related database objects when those changes form one logical schema change.

The initial migration for each database establishes its initial schema.

---

## Docker Initialization vs. Migrations

Docker initialization and database migrations have different responsibilities.

### Docker initialization

The PostgreSQL Docker initialization scripts create the three databases:

```text
dendroflow_metadata
dendroflow_raw
dendroflow_clean
```

They do not manage the ongoing evolution of tables or other schema objects.

### Migrations

Migration files create and modify:

- tables
- constraints
- indexes
- extensions where required
- other database schema objects

Once a database has been initialized, schema changes should be performed through migrations rather than Docker initialization scripts.

This separation ensures that Docker initialization remains focused on creating the development database environment, while migrations provide the version-controlled schema history.

---

## Relationship to Data Architecture

`docs/data-architecture.md` describes the intended data model and the reasoning behind it.

Migration files implement that model in PostgreSQL.

The relationship is:

```text
data-architecture.md
        ↓
conceptual model and design decisions
        ↓
SQL migrations
        ↓
actual PostgreSQL schema
```

Changes to the data architecture should be reflected in corresponding migrations when they affect the implemented database schema.

Not every architectural decision requires a migration. Application-level processing rules, future design considerations, and other non-schema decisions may remain documented without immediately changing the database.

---

## Cross-Database Relationships

The three databases are intentionally separate PostgreSQL databases.

PostgreSQL foreign keys cannot enforce relationships between separate databases.

For example:

```text
RAW sensor_file_interfaces.deployment_id
        ↓
METADATA deployments.deployment_id
```

is an application-managed relationship.

Foreign keys should still be used wherever relationships exist within the same database.

The application is responsible for validating cross-database references where required.

---

## Migration History

Migration files are committed to Git and form the history of the database schema.

Applied migrations must not be edited retroactively.

If a change is required after a migration has been applied, create a new migration.

For example:

```text
001_initial.sql
002_add_location_labels.sql
003_change_deployment_constraints.sql
```

This preserves a reproducible history of schema evolution.

---

## Migration Naming

Migration files use a sequential numeric prefix followed by a short description:

```text
001_initial.sql
002_add_location_labels.sql
003_add_ingestion_metadata.sql
```

The description should communicate the purpose of the migration rather than simply naming an implementation detail.

Migration numbering is maintained independently for each database.

For example:

```text
db/metadata/migrations/001_initial.sql
db/raw/migrations/001_initial.sql
db/clean/migrations/001_initial.sql
```

These migrations are independent even though they share the same number.

---

## PostgreSQL Features

DendroFlow may use PostgreSQL-specific functionality when it provides meaningful benefits for data integrity or the application's requirements.

Examples include:

- `BIGINT GENERATED ALWAYS AS IDENTITY`
- `TIMESTAMPTZ`
- `CHECK` constraints
- foreign keys
- unique constraints
- exclusion constraints
- PostgreSQL extensions where justified

Database-specific functionality should be preferred when it clearly expresses an invariant or requirement rather than avoiding PostgreSQL features for the sake of portability.

---

## Why Plain SQL?

Plain SQL is currently preferred because it:

- makes PostgreSQL behavior explicit
- keeps the project lightweight
- avoids unnecessary ORM abstractions
- makes constraints and indexes easy to review
- provides clear visibility into database design
- keeps database design independent from application implementation details

For a data-engineering project, explicit SQL also makes the database architecture directly inspectable in the repository.

---

## Running migrations

`dendroflow migrate` applies pending SQL migrations to the METADATA, RAW, and
CLEAN databases. Migrations are recorded independently in each database's
`schema_migrations` table. The original SQL files under `db/` remain the
canonical, version-controlled migration history.

For a checkout, run the command from the project root or set
`DENDROFLOW_ROOT` to that root. Installed wheels include copies of the same
SQL files, so migration lookup also works outside a checkout without
`DENDROFLOW_ROOT`. An explicitly configured `DENDROFLOW_ROOT` must contain
`db/`; a missing directory is reported as an error. The build copies the
canonical SQL into the wheel rather than maintaining two source copies.

For an installed wheel, supply PostgreSQL connection settings as process
environment variables. In a checkout the project `.env` can also supply them.
To check the migration CLI from a completely empty schema, run the opt-in
integration test against a **disposable** PostgreSQL instance. The configured
role must be allowed to create databases, and the instance must provide the
`btree_gist` extension required by the METADATA migrations:

```bash
DENDROFLOW_INTEGRATION=1 DENDROFLOW_FRESH_MIGRATION=1 \
  pytest -q tests/integration/test_fresh_migrations.py
```

The test creates three databases with unique `dendroflow_mvp2b_` names,
runs `dendroflow migrate` twice, checks the migration records and key tables,
and drops those databases in cleanup. It does not use the existing
`dendroflow_metadata`, `dendroflow_raw`, or `dendroflow_clean` databases.
The extra `DENDROFLOW_FRESH_MIGRATION=1` flag keeps this database-creation
test out of ordinary integration runs. Installed-wheel acceptance is tracked
separately.

---

## Migration Rules

1. Do not use Docker initialization scripts to evolve existing database schemas.
2. Do not edit migrations that have already been applied.
3. Create a new migration for subsequent schema changes.
4. Keep migrations specific to their target database.
5. Group related schema changes into coherent migrations.
6. Prefer explicit PostgreSQL SQL over unnecessary abstraction.
7. Use database constraints to enforce important invariants where practical.
8. Keep cross-database relationships application-managed.
9. Review schema changes through Git.
10. Keep migration history reproducible.
11. Keep migration files understandable without requiring application code to interpret them.

---

## Current status

PostgreSQL initializes three independently migrated databases:

```text
dendroflow_metadata
dendroflow_raw
dendroflow_clean
```

The migrations in `db/metadata/migrations/`, `db/raw/migrations/`, and
`db/clean/migrations/` are present. `docs/data-architecture.md` explains
the data model. Docker initialization creates the database names on an empty
volume, and `dendroflow migrate` installs or advances their schemas.
