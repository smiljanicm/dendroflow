# Database Migrations

## Purpose

DendroFlow uses version-controlled database migrations to create and evolve its PostgreSQL database schemas.

The migration strategy is designed to keep schema changes:

- explicit and reviewable
- reproducible across environments
- tied to Git history
- independent of Docker's initial database setup
- understandable without requiring an ORM

## Database Structure

DendroFlow uses three separate PostgreSQL databases:

- `dendroflow_metadata`
- `dendroflow_raw`
- `dendroflow_clean`

Each database has its own migration sequence.

The database separation reflects the conceptual distinction between:

- **METADATA** — what the monitoring/research system is
- **RAW** — what data was received and how it was ingested
- **CLEAN** — the canonical processed data product

Cross-database relationships are application-managed rather than PostgreSQL foreign keys.

## Migration Approach

DendroFlow initially uses **plain SQL migration files**.

The repository structure is:

```text
db/
├── metadata/
│   └── migrations/
├── raw/
│   └── migrations/
└── clean/
    └── migrations/
```

Migration files are numbered to establish a deterministic execution order:

```text
001_initial.sql
002_add_location_labels.sql
003_...
```

SQL is intentionally kept visible rather than generated through an ORM. Database structure is considered an important part of the DendroFlow architecture and should be directly inspectable in the repository.

## Docker Initialization vs. Migrations

Docker PostgreSQL initialization and database migrations have different responsibilities.

### Docker initialization

Files under:

```text
docker/postgres/init/
```

are responsible for initializing the PostgreSQL instance itself.

The current initialization script creates the three DendroFlow databases:

```text
dendroflow_metadata
dendroflow_raw
dendroflow_clean
```

These scripts are executed by the PostgreSQL Docker image when the database data directory is initialized for the first time.

They are **not** the mechanism for evolving an existing schema.

### Database migrations

Migration files are responsible for creating and modifying tables, constraints, indexes, and other schema objects within the three databases.

A schema change should therefore result in a new migration rather than editing an already-applied migration.

For example:

```text
001_initial.sql
002_add_location_labels.sql
```

After `001_initial.sql` has been applied, its contents should be treated as immutable.

## Migration History

Migration files are stored in Git and form part of the project's database history.

A migration should:

1. have a unique sequential identifier
2. describe one coherent schema change
3. be committed together with the application code that depends on it, when applicable
4. not modify previously applied migrations

The initial implementation may apply migrations explicitly rather than through a dedicated migration framework.

Migration automation can be introduced later without changing the underlying SQL migration strategy.

## Why Plain SQL?

Plain SQL is the initial choice because DendroFlow is currently small enough that a dedicated migration framework would add complexity without providing significant immediate benefit.

The approach provides:

- direct visibility into PostgreSQL schema changes
- full control over PostgreSQL-specific features and constraints
- simple Git diffs and code review
- minimal dependencies
- a clear separation between database design and application code

This also keeps the database implementation aligned with the architectural goal of treating PostgreSQL as a first-class component of DendroFlow rather than merely as storage behind an ORM.

## Future Migration Tooling

As DendroFlow grows, manually applying migrations may become inconvenient.

Potential future improvements include a small migration runner that:

- tracks applied migrations
- applies only pending migrations
- verifies migration order
- integrates with development and CI workflows

A mature migration framework such as Alembic may also be considered if the project later adopts SQLAlchemy or develops more substantial application infrastructure.

Such tooling is intentionally deferred until there is a concrete operational need.

## Migration Rules

The following rules apply to database schema development:

1. **Do not use Docker initialization scripts to evolve an existing database.**
2. **Do not edit migrations that have already been applied.**
3. **Create a new migration for each subsequent schema change.**
4. **Keep migrations specific to their target database.**
5. **Prefer explicit PostgreSQL SQL over unnecessary abstraction.**
6. **Schema changes should be reviewed as part of the Git history.**
7. **Migration tooling should be introduced when it solves an actual problem, not simply for additional abstraction.**

## Current Status

The PostgreSQL infrastructure is established through Docker Compose.

The three databases exist and are independently accessible.

The next step is to create the initial migrations for the DendroFlow schemas.