-- Preserve every differing overlap that was skipped during successful ingestion.
CREATE TABLE raw_observation_conflicts (
    conflict_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingestion_run_id BIGINT NOT NULL REFERENCES ingestion_runs(ingestion_run_id),
    location_id BIGINT NOT NULL,
    variable_id BIGINT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    stored_interface_id BIGINT NOT NULL REFERENCES sensor_file_interfaces(interface_id),
    incoming_interface_id BIGINT NOT NULL
        REFERENCES sensor_file_interfaces(interface_id),
    stored_value DOUBLE PRECISION NOT NULL,
    incoming_value DOUBLE PRECISION NOT NULL,
    incoming_source_row_number BIGINT NOT NULL CHECK (incoming_source_row_number > 0),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT raw_observation_conflicts_per_run_unique UNIQUE (
        ingestion_run_id, location_id, variable_id, timestamp,
        incoming_interface_id, incoming_source_row_number
    )
);

CREATE INDEX raw_observation_conflicts_run_idx
    ON raw_observation_conflicts(ingestion_run_id);
