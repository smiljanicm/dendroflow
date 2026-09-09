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

DendroFlow is under active development. Documentation is updated as individual architectural components reach a stable implementation.
