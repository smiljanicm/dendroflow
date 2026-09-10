# DendroFlow Data Architecture

## Purpose

DendroFlow is an open-source, configuration-driven data management system for environmental and plant sensor monitoring.

The data architecture separates:

- research and monitoring metadata
- received source data and ingestion provenance
- processed, canonical data products

The architecture is designed to preserve source data, maintain traceable provenance, and allow processed datasets to be reproduced from their inputs and configuration.

---

## Database Architecture

DendroFlow uses three separate PostgreSQL databases:

```text
dendroflow_metadata
dendroflow_raw
dendroflow_clean
```

The databases have distinct responsibilities.

### METADATA

Describes what the research and monitoring system is.

Examples include:

- sites and locations
- sensor types and models
- physical sensors
- monitored variables
- sensor deployments
- broader research metadata that may be added in the future

### RAW

Database:

```text
dendroflow_raw
```

The RAW database records source definitions, exact source-file versions, imported observations, and ingestion provenance.

The implemented RAW model separates six concerns:

```text
files
    logical source definitions

file_versions
    immutable snapshots of exact source content

ingestion_targets
    intended file-version/interface set for a run

ingestion_batches
    processing progress and retry history

ingestion_interfaces
    successful completion markers

raw_observations
    imported observations and source-line provenance
```

The relationship is approximately:

```text
files
  │
  ├── sensor_file_interfaces
  │
  └── file_versions

ingestion_runs
    │
    ├── ingestion_targets -> file_versions + interfaces
    ├── ingestion_batches -> file_versions
    ├── raw_observations
    └── ingestion_interfaces -> file_versions + interfaces
```

### CLEAN

Contains the canonical processed data product produced by DendroFlow.

The initial structural schema is implemented and provides:

- clean datasets
- canonical observations
- RAW-to-CLEAN provenance
- quality flags
- observation-level quality assignments

Processing rules, transformation configuration, and quality-control workflows are implemented separately from the structural schema and remain part of the CLEAN processing phase.

---

## Core Data Model

A central architectural principle is that the following concepts are distinct:

```text
physical sensor
      ↓
deployment
      ↓
file interface
      ↓
raw observation
      ↓
clean observation
```

These concepts should not be collapsed into a single entity.

A physical sensor may be deployed multiple times and may provide multiple variables.

A deployment represents a particular combination of:

- physical sensor
- monitored variable
- location
- validity period

A source file may contain data from one or more deployments, and a deployment may be represented in multiple source files.

---

# Metadata Database

Database:

```text
dendroflow_metadata
```

The metadata database is intentionally broader than sensor monitoring alone. It may eventually contain information about inventory, sampling, experiments, genetics, and other research context.

## `sites`

Represents sites and hierarchical site groupings.

```text
sites
-----
site_id
name
description
latitude
longitude
parent_id
site_code
```

### Semantics

- `site_id` is the database identity.
- `name` is the human-readable site name.
- `description` provides additional information.
- `latitude` and `longitude` represent optional site-level coordinates.
- `parent_id` provides hierarchical relationships between sites.
- `site_code` is a unique, stable, human-usable site identifier.

`site_code` is intentionally distinct from `site_id`. The former is a semantic identifier; the latter is the database primary key.

Site labels are not versioned. Where historical labels are required for individual monitoring locations, they are represented through `location_labels`.

---

## `location_types`

Defines the controlled vocabulary for location types.

```text
location_types
--------------
location_type_id
type
description
```

Examples may include:

```text
tree
stem
branch
soil
air
tower
plot
building
```

`name` is unique.

The separate table provides a controlled vocabulary without hard-coding location types throughout the application.

---

## `locations`

Represents a monitoring or research location within a site.

```text
locations
---------
location_id
site_id
location_type_id
latitude
longitude
height_above_ground
azimuth
```

A location is deliberately modeled independently from a physical sensor.

### Horizontal position

`latitude` and `longitude` provide optional coordinates for the location.

When supplied, both coordinates should be present.

Valid ranges are:

```text
-90 ≤ latitude ≤ 90
-180 ≤ longitude ≤ 180
```

### Vertical position

`height_above_ground` records vertical position relative to ground level.

It may be:

- negative for below-ground locations
- zero for ground level
- positive for above-ground locations

### Orientation

`azimuth` records horizontal orientation in degrees.

Valid values are:

```text
0 ≤ azimuth < 360
```

The value is nullable because orientation is not relevant to every location.

### Location identity

A location does not require a separate tree identifier. A tree, stem, branch, soil position, or other entity can be represented through the combination of the location and its location type.

---

## `location_labels`

Stores labels associated with locations and preserves their history.

```text
location_labels
---------------
location_label_id
location_id
label
valid_from
valid_to
```

A location may have different labels over time.

For example:

```text
Location 17

2024-01-01 → 2025-07-01   Tree 12
2025-07-01 → NULL         Tree 18
```

Validity periods should not overlap for the same location.

Validity intervals use half-open semantics:

```text
[valid_from, valid_to)
```

This allows one label to end at exactly the instant another label begins without creating an overlap.

---

## `sensor_types`

Defines broad categories of sensors.

```text
sensor_types
------------
sensor_type_id
type
description
```

`type` identifies the sensor category.

---

## `sensor_models`

Defines specific sensor models.

```text
sensor_models
-------------
sensor_model_id
model
manufacturer
sensor_type_id
```

A sensor model belongs to a sensor type.

---

## `sensors`

Represents a physical sensor.

```text
sensors
-------
sensor_id
sensor_model_id
serial_number
description
```

A physical sensor is distinct from its deployments.

The same physical sensor may be deployed at different locations or used for different variables over time.

---

## `variables`

Defines measured and derived variables.

```text
variables
---------
variable_id
variable
derived
description
```

`variable` is unique.

`derived` distinguishes variables directly measured by a sensor from variables calculated by DendroFlow.

Units are intentionally **not** stored on the variable.

The same conceptual variable may be represented using different units by different sensors, files, or deployments. Unit information therefore belongs to the source/interface or processed-data context where appropriate.

---

## `deployments`

Represents the use of a physical sensor for a particular variable at a particular location during a validity period.

```text
deployments
-----------
deployment_id
sensor_id
location_id
variable_id
valid_from
valid_to
```

A deployment combines:

```text
sensor + variable + location + validity period
```

A multi-channel sensor can therefore have multiple deployments, effectively one deployment per monitored variable/channel.

For example:

```text
Sensor 42

Temperature → Location A → 2025-01-01 → NULL
Humidity    → Location A → 2025-01-01 → NULL
```

If the temperature channel fails while humidity continues to operate, the temperature deployment can end independently.

The same physical sensor may also have successive deployments at different locations.

For a given `sensor_id` and `variable_id`, deployment validity periods should not overlap.

---

# RAW Database

Database:

```text
dendroflow_raw
```

The RAW database stores registered source files, immutable file versions, ingestion state, provenance, and normalized observations.

Its main responsibilities are:

- defining how source files are read
- mapping source columns to metadata deployments
- identifying exact file contents using SHA-256 fingerprints
- recording ingestion targets and batch progress
- supporting retry and resume after interruption
- preserving physical source-line provenance
- preventing duplicate re-ingestion of an already completed file version

The main RAW entities are:

```text
files
file_versions
sensor_file_interfaces
ingestion_runs
ingestion_targets
ingestion_batches
ingestion_interfaces
raw_observations
```

RAW ingestion preserves received measurements and provenance but does not perform scientific cleaning, quality control, aggregation, or unit normalization.

Detailed ingestion behavior is documented in [RAW ingestion](raw-ingestion.md).

---

# CLEAN Database

Database:

```text
dendroflow_clean
```

The CLEAN database stores canonical processed datasets derived from RAW observations.

The initial structural schema is implemented and contains:

```text
clean_datasets
quality_flags
clean_observations
clean_observation_inputs
clean_observation_quality
```

## `clean_datasets`

Identifies a reproducible processed dataset.

```text
clean_datasets
--------------
clean_dataset_id
name
description
created_at
```

`description` is stored as JSONB so dataset-level processing metadata can be represented in a structured form.

## `clean_observations`

Stores canonical processed observations.

```text
clean_observations
------------------
clean_observation_id
clean_dataset_id
location_id
variable_id
timestamp
value
quality_status
```

`quality_status` is constrained to:

```text
valid
suspect
invalid
```

Within a clean dataset, observations are unique by:

```text
(clean_dataset_id, location_id, variable_id, timestamp)
```

## `clean_observation_inputs`

Records which RAW observations contributed to a CLEAN observation.

```text
clean_observation_inputs
------------------------
clean_observation_id
raw_observation_id
```

This relationship provides provenance from processed values back to their RAW inputs.

Because RAW and CLEAN are separate PostgreSQL databases, `raw_observation_id` is an application-managed cross-database reference.

## `quality_flags`

Defines machine-readable quality-control flags.

```text
quality_flags
-------------
quality_flag_id
code
description
```

## `clean_observation_quality`

Associates quality flags with individual CLEAN observations.

```text
clean_observation_quality
-------------------------
clean_observation_id
quality_flag_id
```

The structural CLEAN schema is therefore established. The processing rules, configuration model, transformations, and quality-control workflow will be implemented during the CLEAN processing phase.

Potential CLEAN responsibilities include:

- unit normalization
- duplicate resolution
- quality control
- outlier handling
- justified timestamp correction
- aggregation
- derived variables
- processing provenance

CLEAN data should remain reproducible from its metadata, RAW inputs, and processing configuration.

The distinction between RAW and CLEAN is fundamental:

> **RAW preserves received measurements and ingestion provenance. CLEAN represents the canonical processed data product produced by DendroFlow.**

---

# Timestamp and Timezone Semantics

DendroFlow distinguishes between a timestamp's **source representation** and the **instant in time** it represents.

## Source timestamps

A source file may contain a timestamp without an explicit timezone:

```text
2026-07-01 10:00
```

The associated `files.timestamp_timezone` provides the information needed to interpret that timestamp.

For example:

```text
2026-07-01 10:00 Europe/Berlin
```

represents:

```text
2026-07-01 08:00 UTC
```

The source timezone is retained as file metadata for provenance.

The source timezone must describe the clock semantics actually used by the source system. A fixed-offset timezone is appropriate when a logger uses a fixed clock throughout the year, even if the monitoring site is geographically located in a daylight-saving timezone.

## Normalized timestamps

Once interpreted, timestamps representing actual instants are stored using PostgreSQL `TIMESTAMPTZ`.

This applies to:

- observation timestamps
- deployment validity periods
- location-label validity periods
- ingestion timestamps

`TIMESTAMPTZ` represents an instant in time rather than preserving the original timezone representation.

The original source timezone remains available through the associated file metadata where required for provenance.

## Different source timezones

Different files associated with the same deployment may use different timezones.

For example:

```text
file_A: 10:00 Europe/Berlin
file_B: 08:00 UTC
```

These represent the same instant.

Conversely:

```text
file_A: 10:00 Europe/Berlin
file_B: 10:00 UTC
```

represent different instants.

Timestamp normalization must therefore occur during ingestion using the timezone associated with the source representation.

## Display timezone

The timezone used to display or analyze timestamps is separate from the source timezone.

Stored timestamps represent instants and should not be modified merely to accommodate a user's preferred display timezone.

Applications and analysis tools may display the same instant in an appropriate timezone when required.

---

# Referential Integrity

Foreign keys are used wherever relationships exist within the same PostgreSQL database.

The three databases are intentionally separate, so PostgreSQL foreign keys cannot enforce relationships between them.

For example:

```text
RAW sensor_file_interfaces.deployment_id
        ↓
METADATA deployments.deployment_id
```

is an application-managed relationship.

Cross-database references should therefore be validated by DendroFlow application logic.

---

# Data Integrity Principles

The database should enforce important invariants wherever practical.

Examples include:

### Coordinates

```text
-90 ≤ latitude ≤ 90
-180 ≤ longitude ≤ 180
```

A coordinate pair must contain either both latitude and longitude or neither.

### Azimuth

```text
0 ≤ azimuth < 360
```

### Temporal validity

Validity periods must have:

```text
valid_to > valid_from
```

when an end time is present.

Location labels for the same location must not overlap.

Deployments for the same sensor and variable must not have overlapping validity periods.

### Controlled identifiers

Canonical identifiers such as:

- `site_code`
- variable names
- location type names

should have uniqueness constraints where defined by the data model.

---

# Scalability and Performance

The metadata database is expected to be substantially smaller than the observation databases.

Nevertheless, the core identifiers use PostgreSQL `BIGINT` identity columns to avoid unnecessarily constraining future deployments of DendroFlow across multiple laboratories, projects, or collaborating institutions.

Performance optimization is deliberately deferred until actual usage patterns are known.

Potential future considerations include:

- additional indexes
- PostgreSQL table partitioning
- PostGIS
- retention policies
- bulk ingestion optimizations
- storage and archival strategies

These should be introduced based on measured requirements rather than assumed scale.

---

# Architectural Principles

The current architecture follows several guiding principles:

1. **Separate metadata, RAW, and CLEAN responsibilities.**
2. **Preserve received source data rather than destructively modifying it.**
3. **Maintain provenance from observations back to their source files and ingestion runs.**
4. **Keep physical sensors separate from deployments.**
5. **Treat deployments as sensor-variable-location validity periods.**
6. **Associate source timezone with the file representation, not automatically with the deployment.**
7. **Normalize timestamps to actual instants while retaining source timezone information for provenance.**
8. **Use database constraints to enforce important data invariants.**
9. **Use application-managed references between the three databases.**
10. **Prefer a simple architecture that can evolve as DendroFlow grows.**

This document describes the current architectural baseline. Implementation details may evolve as requirements become clearer, but changes to these principles should be deliberate and documented.