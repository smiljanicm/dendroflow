# DendroFlow

Open-source, configuration-driven data management tool for monitoring environmental conditions and plant physiology.

DendroFlow aims to provide a reproducible, maintainable workflow for managing data from environmental and plant-physiology monitoring systems.

## Project status

DendroFlow is currently under active development.

The initial development focuses on:

- structured metadata for monitoring networks (sites, sensors, variables)
- sensor and instrument data handling
- raw data ingestion and provenance tracking
- data cleaning and transformation
- configuration-driven processing

## Documentation

- [Data architecture](docs/data-architecture.md) — overall METADATA, RAW, and CLEAN data model
- [RAW ingestion](docs/raw-ingestion.md) — file versioning, provenance, batching, retries, and resume behavior
- [Database migrations](docs/database-migrations.md) — migration structure and execution
- [Ingestion CLI](docs/ingestion-cli.md) — run registered files and interpret text or JSON results
- [Configuration persistence](docs/configuration-persistence.md) — METADATA and RAW persistence, public apply functions, transaction outcomes, and recovery boundaries
- [Configuration CLI](docs/configuration-cli.md) — validation, planning, confirmation, apply outcomes, and recovery
- [Configuration workbook workflow](docs/configuration-workbook.md) — Excel export, validation, conversion to YAML, supported changes, and review before apply

DendroFlow is under active development. Documentation is updated as individual architectural components reach a stable implementation.
