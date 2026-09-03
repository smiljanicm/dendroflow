-- DendroFlow RAW database
-- Initial schema

CREATE TABLE files (
    file_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    filepath TEXT NOT NULL UNIQUE,
    timestamp_timezone TEXT NOT NULL,
    timestamp_format TEXT NOT NULL
);


CREATE TABLE file_versions (
    file_version_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    file_id BIGINT NOT NULL,
    file_hash TEXT NOT NULL,
    file_size BIGINT NOT NULL,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT file_versions_file_fk
        FOREIGN KEY (file_id)
        REFERENCES files(file_id),

    CONSTRAINT file_versions_file_hash_unique
        UNIQUE (file_id, file_hash),

    CONSTRAINT file_versions_file_size_check
        CHECK (file_size >= 0)
);


CREATE TABLE sensor_file_interfaces (
    interface_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    file_id BIGINT NOT NULL,
    deployment_id BIGINT NOT NULL,

    values_column TEXT NOT NULL,
    timestamp_column TEXT NOT NULL,
    unit TEXT,

    CONSTRAINT sensor_file_interfaces_file_fk
        FOREIGN KEY (file_id)
        REFERENCES files(file_id),

    CONSTRAINT sensor_file_interfaces_file_column_unique
        UNIQUE (file_id, values_column)
);


CREATE TABLE ingestion_runs (
    ingestion_run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,

    status TEXT NOT NULL,

    CONSTRAINT ingestion_runs_status_check
        CHECK (status IN ('running', 'completed', 'failed')),

    CONSTRAINT ingestion_runs_finished_check
        CHECK (
            finished_at IS NULL
            OR finished_at >= started_at
        )
);


CREATE TABLE ingestion_interfaces (
    ingestion_run_id BIGINT NOT NULL,
    file_version_id BIGINT NOT NULL,
    interface_id BIGINT NOT NULL,

    CONSTRAINT ingestion_interfaces_pkey
        PRIMARY KEY (
            ingestion_run_id,
            file_version_id,
            interface_id
        ),

    CONSTRAINT ingestion_interfaces_run_fk
        FOREIGN KEY (ingestion_run_id)
        REFERENCES ingestion_runs(ingestion_run_id),

    CONSTRAINT ingestion_interfaces_version_fk
        FOREIGN KEY (file_version_id)
        REFERENCES file_versions(file_version_id),

    CONSTRAINT ingestion_interfaces_interface_fk
        FOREIGN KEY (interface_id)
        REFERENCES sensor_file_interfaces(interface_id)
);


CREATE TABLE raw_observations (
    observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    location_id BIGINT NOT NULL,
    variable_id BIGINT NOT NULL,

    timestamp TIMESTAMPTZ NOT NULL,
    value DOUBLE PRECISION NOT NULL,

    interface_id BIGINT NOT NULL,
    ingestion_run_id BIGINT NOT NULL,
    source_row_number BIGINT NOT NULL,

    CONSTRAINT raw_observations_identity_unique
        UNIQUE (
            location_id,
            variable_id,
            timestamp
        ),

    CONSTRAINT raw_observations_source_row_check
        CHECK (source_row_number > 0),

    CONSTRAINT raw_observations_interface_fk
        FOREIGN KEY (interface_id)
        REFERENCES sensor_file_interfaces(interface_id),

    CONSTRAINT raw_observations_ingestion_run_fk
        FOREIGN KEY (ingestion_run_id)
        REFERENCES ingestion_runs(ingestion_run_id)
);


CREATE INDEX file_versions_file_id_idx
    ON file_versions(file_id);


CREATE INDEX sensor_file_interfaces_file_id_idx
    ON sensor_file_interfaces(file_id);


CREATE INDEX ingestion_interfaces_file_version_id_idx
    ON ingestion_interfaces(file_version_id);


CREATE INDEX ingestion_interfaces_interface_id_idx
    ON ingestion_interfaces(interface_id);


CREATE INDEX raw_observations_interface_id_idx
    ON raw_observations(interface_id);


CREATE INDEX raw_observations_ingestion_run_id_idx
    ON raw_observations(ingestion_run_id);

