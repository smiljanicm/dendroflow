# DendroFlow — Data Architecture

**Status:** Architecture baseline
**Date:** 2026-09-01

## 1. Purpose

This document records the architectural decisions made during DendroFlow development.

The goal is to establish a stable data model before implementation begins.

The architecture separates:

1. research and monitoring metadata;
2. acquired source data and ingestion provenance;
3. processed and canonical data.

---

## 2. Core architectural principle

DendroFlow follows three conceptual data layers:

```text
METADATA
    │
    ▼
RAW
    │
    ▼
CLEAN
```

### Metadata

Describes the physical and scientific monitoring context:

- sites;
- observation locations;
- sensors;
- variables;
- deployments;
- related research metadata.

### RAW

Preserves acquired source data and its provenance.

RAW should be as close as practical to the source data and should not apply scientific or quality-control interpretation.

### CLEAN

Contains canonical, processed observations produced from RAW data using defined processing rules.

The fundamental principle is:

> **RAW preserves what was received. CLEAN represents what DendroFlow considers the canonical data product.**

---

# 3. Database architecture

DendroFlow will use three separate PostgreSQL databases:

```text
dendroflow_metadata
dendroflow_raw
dendroflow_clean
```

## 3.1 Metadata database

The metadata database is intentionally broader than sensor monitoring.

It represents the research environment and can later support other types of scientific metadata such as:

- inventory;
- sampling;
- genetics;
- experiments;
- other research entities.

The current model is divided conceptually into:

```text
dendroflow_metadata
│
├── spatial / research context
│   ├── sites
│   ├── locations
│   ├── location_types
│   └── location_labels
│
└── monitoring metadata
    ├── sensor_types
    ├── sensor_models
    ├── sensors
    ├── variables
    └── deployments
```

These remain in one database because the relationships between locations and monitoring entities are tightly coupled and benefit from normal PostgreSQL foreign-key constraints.

A future schema-level separation may be introduced if useful, without necessarily splitting the database.

---

# 4. Sites

A site represents a geographical or organizational monitoring area.

```text
sites
-----
site_id
name
description
latitude
longitude
parent_id
short_name
```

## Decisions

- Sites may have a parent site.
- `parent_id` references `sites.site_id`.
- Existing site hierarchy is retained.
- GPS is represented by separate latitude and longitude values rather than a PostgreSQL `point`.
- Site label history is not required.

---

# 5. Location types

Location types describe the functional category of an observation location.

```text
location_types
--------------
location_type_id
name
description
```

Examples include:

```text
tree
site
vertical_profile
```

`name` should be unique.

---

# 6. Observation locations

A location represents a physical observation position within a site.

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

## Spatial attributes

### Latitude / longitude

Define the horizontal position of the observation location.

### Height above ground

May be positive, zero, or negative.

Examples:

```text
+10.0 m  above ground
 +1.3 m  above ground
  0.0 m  ground level
 -0.2 m  below ground
```

### Azimuth

Defines horizontal orientation relative to north.

```text
0°   North
90°  East
180° South
270° West
```

Azimuth is nullable where orientation is not meaningful.

## Design decision

No separate `tree_id` entity is currently required.

Tree-related observation positions can be represented as locations, with human-facing tree identifiers handled through location labels.

---

# 7. Location labels

Human-facing labels are modeled separately because labels may change over time.

```text
location_labels
---------------
location_label_id
location_id
label
valid_from
valid_to
```

Example:

```text
location_id = 101

2024-01-01 → 2025-05-31   Tree 17
2025-06-01 → NULL         Tree 23
```

The physical location remains the same while its label changes.

## Temporal rule

A location should not have overlapping label validity periods.

The exact PostgreSQL constraint will be implemented later.

---

# 8. Sensor types

Sensor types represent functional categories of instruments.

```text
sensor_types
------------
sensor_type_id
short_type
description
```

Examples:

```text
temperature_humidity
dendrometer
soil_moisture
radiation
```

---

# 9. Sensor models

Sensor models represent commercially or technically defined instrument models.

```text
sensor_models
-------------
sensor_model_id
model
manufacturer
sensor_type_id
description
```

Relationship:

```text
sensor_models.sensor_type_id
        ↓
sensor_types.sensor_type_id
```

---

# 10. Sensors

A sensor represents an individual physical instrument.

```text
sensors
-------
sensor_id
sensor_model_id
serial_number
description
```

Relationship:

```text
sensor_type
     ↓
sensor_model
     ↓
physical sensor
```

The same sensor may be deployed multiple times at different locations and/or periods.

A likely uniqueness constraint is:

```text
(sensor_model_id, serial_number)
```

rather than assuming serial numbers are globally unique.

---

# 11. Variables

Variables represent the semantic measurement being recorded.

```text
variables
---------
variable_id
name
derived
description
```

## Decisions

- `name` is unique.
- `derived` distinguishes measured variables from variables produced by processing.
- Units are **not** stored here.

Examples:

```text
Air Temperature
Relative Humidity
Stem Diameter
Soil Temperature
```

---

# 12. Deployments

A deployment represents one physical sensor measuring one variable at one observation location during a defined period.

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

This is a central modeling decision.

## Multi-channel sensors

A sensor measuring multiple variables gets multiple deployments.

Example:

```text
Sensor 42
│
├── Deployment 101 → Air Temperature
└── Deployment 102 → Relative Humidity
```

This allows individual channels to fail or be replaced independently.

For example, temperature may stop while relative humidity continues.

## Sensor replacement

A replacement sensor receives a new deployment.

```text
Sensor 42
    └── Deployment 101
        2024 → 2025

Sensor 57
    └── Deployment 205
        2025 → ...
```

## Temporal rule

For a given sensor and variable, deployment periods should not overlap.

The exact PostgreSQL constraint will be implemented later.

---

# 13. Files

A file represents an acquired source-file artifact.

```text
files
-----
file_id
filepath
hash
timestamp_timezone
```

## Decisions

- `filepath` identifies the acquired file path.
- `hash` is used for content/integrity checking.
- `last_updated` is not required.
- File processing state is not stored directly on the file.
- `timestamp_timezone` describes how timestamps in the file should be interpreted.

Because source files are generally wide:

```text
timestamp | temperature | RH | dendrometer | ...
```

the timestamp interpretation belongs to the file rather than each sensor-value interface.

For now, timezone metadata remains at file level. A higher-level acquisition/source entity may be introduced later if repeated information becomes significant.

---

# 14. Sensor-file interfaces

A sensor-file interface maps a particular source-file column to a deployment.

```text
sensor_file_interfaces
----------------------
interface_id
file_id
deployment_id
values_column
timestamp_column
unit
```

An interface represents:

> One value column in one file mapped to one deployment.

Example:

```text
timestamp | temp | RH
              │     │
              ▼     ▼
          interface interface
              │     │
              ▼     ▼
        deployment deployment
```

## Decisions

- `deployment_id` is the semantic link to sensor, location, and variable.
- Sensor, location, and variable IDs are not redundantly stored here.
- `unit` belongs to the interface because the same variable may be represented in different units in different files.
- `timestamp_column` belongs here because files may have different column layouts.
- `timestamp_timezone` belongs to `files`.
- A reusable interface/template abstraction is intentionally deferred.

---

# 15. Ingestion runs

An ingestion run represents one execution of the ingestion process.

```text
ingestion_runs
--------------
ingestion_run_id
started_at
finished_at
status
```

Initial statuses may include:

```text
running
completed
failed
```

Additional states may be added later.

---

# 16. Ingestion interfaces

Processing progress is tracked at interface level rather than file level.

```text
ingestion_interfaces
--------------------
ingestion_run_id
interface_id
```

The intended primary key is:

```text
PRIMARY KEY (ingestion_run_id, interface_id)
```

The meaning of a row is:

> The interface was successfully processed during this ingestion run.

This enables fine-grained recovery.

Example:

```text
Ingestion Run 42

Interface 1 → completed
Interface 2 → completed
Interface 3 → failed
Interface 4 → not started
```

On restart:

```text
Interface 1 → skip
Interface 2 → skip
Interface 3 → retry
Interface 4 → process
```

The completion record should be committed transactionally with the corresponding observation insertion.

---

# 17. RAW observations

RAW observations are currently modeled as:

```text
raw_observations
----------------
observation_id
timestamp
value
interface_id
ingestion_run_id
```

Through `interface_id`, an observation can be traced to:

```text
file
deployment
sensor
location
variable
source column
unit
```

Through `ingestion_run_id`, the ingestion execution is known.

---

# 18. RAW data philosophy

RAW is intentionally non-destructive.

RAW should not perform:

- deduplication;
- outlier removal;
- gap filling;
- unit conversion;
- quality-control correction;
- derived-variable calculation.

If the source file contains:

```text
timestamp   value
10:00       21.4
10:00       21.5
```

both observations are retained.

There is therefore no uniqueness constraint such as:

```text
UNIQUE(interface_id, timestamp)
```

that would destroy legitimate source duplicates.

---

# 19. Re-ingestion behavior

There is an important distinction between:

### Genuine source duplicates

If the source file itself contains duplicate observations, they are preserved.

Example:

```text
10:00 | 21.4
10:00 | 21.4
```

Both source rows remain represented in RAW.

### Re-ingestion duplicates

If an already-ingested file is encountered again, the same source observation should not create another RAW observation.

The effective duplicate check is based on the source context and observation content:

```text
file
+
variable
+
timestamp
+
value
```

The implementation must distinguish these two situations:

```text
same observation encountered again
        → skip

duplicate observation genuinely present in source
        → preserve
```

The exact database implementation is deferred to RAW ingestion development.

---

# 20. CLEAN database

The CLEAN database represents the canonical processed data product.

The detailed CLEAN schema is intentionally not yet defined.

Conceptually:

```text
RAW
 │
 │ configured processing
 ▼
CLEAN
```

CLEAN is responsible for operations such as:

- unit conversion;
- duplicate resolution;
- quality-control rules;
- outlier handling;
- timestamp correction where appropriate;
- aggregation;
- derived variables;
- other configured transformations.

The guiding distinction is:

```text
RAW:
"What did we receive?"

CLEAN:
"What do we consider the canonical observation?"
```

CLEAN should be reproducible from appropriate combinations of:

```text
METADATA
+
RAW
+
processing configuration
```

---

# 21. Current entity inventory

## Metadata database

```text
sites
location_types
locations
location_labels

sensor_types
sensor_models
sensors
variables
deployments
```

## RAW database

```text
files
sensor_file_interfaces

ingestion_runs
ingestion_interfaces

raw_observations
```

## CLEAN database

Detailed entities to be designed later.

---

# 22. Important constraints

The following constraints are part of the intended model.

## Referential integrity

Foreign keys should be used for relationships within each database.

Because the databases are separate, cross-database references cannot use normal PostgreSQL foreign keys.

For example:

```text
dendroflow_raw.sensor_file_interfaces.deployment_id
        ↓
dendroflow_metadata.deployments.deployment_id
```

is a cross-database reference and must be maintained as an application-level contract.

## Spatial validation

```text
-90  ≤ latitude  ≤ 90
-180 ≤ longitude ≤ 180
0    ≤ azimuth   < 360
```

## Uniqueness

Likely uniqueness constraints include:

```text
location_types.name
variables.name
files.filepath
(sensor_model_id, serial_number)
```

## Temporal integrity

No overlapping validity periods for:

```text
location labels for the same location
```

or:

```text
deployments for the same sensor + variable
```

## Ingestion integrity

```text
(ingestion_run_id, interface_id)
```

must be unique.

## RAW observations

No uniqueness constraint should eliminate genuine source duplicates.

---

# 23. Explicitly deferred decisions

The following are intentionally left for later sessions.

### CLEAN schema

Exact tables and relationships have not yet been designed.

### Processing configuration

The configuration model for cleaning, transformation, and derived variables will be designed later.

### RAW duplicate implementation

The required behavior is defined, but the exact SQL/algorithm is deferred.

### Timestamp implementation details

The architectural decision is:

```text
timestamp interpretation → file level
```

The exact PostgreSQL timestamp type and handling of timezone/DST edge cases will be finalized during ingestion implementation.

### Reusable file-interface definitions

Not required in the initial implementation.

### Advanced ingestion logging

Detailed error and logging infrastructure is deferred.

### Performance optimization

Partitioning, specialized indexes, retention policies, and other large-scale optimizations are deferred until actual data characteristics justify them.

### Operational security and production deployment

Users, permissions, backups, production deployment, and retention policies are outside the scope of the initial architecture.

---

# 24. High-level architecture

```text
                         DENDROFLOW
                              │
             ┌────────────────┼────────────────┐
             │                │                │
             ▼                ▼                ▼

   ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
   │    METADATA     │ │      RAW        │ │      CLEAN      │
   │                 │ │                 │ │                 │
   │ Sites           │ │ Files           │ │ Canonical       │
   │ Locations       │ │ Interfaces      │ │ observations    │
   │ Labels          │ │ Ingestion runs  │ │                 │
   │ Sensors         │ │ Ingestion state │ │ Derived data    │
   │ Variables       │ │ RAW observations│ │                 │
   │ Deployments     │ │                 │ │ Processing      │
   │                 │ │                 │ │ provenance      │
   └────────┬────────┘ └────────┬────────┘ └────────┬────────┘
            │                   │                   │
            │                   │                   │
            └─────── context ───┴────── processing ─┘
```

---

# 25. Architecture status

DendroFlow architecture is considered **complete at the conceptual level**.

The model intentionally distinguishes:

```text
physical sensor
      ≠
deployment
      ≠
file interface
      ≠
raw observation
      ≠
clean observation
```

This separation provides:

- clear provenance;
- support for sensor replacement;
- support for multi-channel sensors;
- support for multiple acquisition streams;
- preservation of source data;
- reproducible processing;
- future extensibility beyond sensor monitoring.

The next development phase can therefore focus on implementing the architecture rather than continuing to redesign the core model.
