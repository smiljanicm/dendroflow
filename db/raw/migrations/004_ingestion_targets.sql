CREATE TABLE ingestion_targets (
    ingestion_run_id BIGINT NOT NULL,
    file_version_id BIGINT NOT NULL,
    interface_id BIGINT NOT NULL,

    CONSTRAINT ingestion_targets_pkey
        PRIMARY KEY (
            ingestion_run_id,
            file_version_id,
            interface_id
        ),

    CONSTRAINT ingestion_targets_run_fk
        FOREIGN KEY (ingestion_run_id)
        REFERENCES ingestion_runs(ingestion_run_id),

    CONSTRAINT ingestion_targets_version_fk
        FOREIGN KEY (file_version_id)
        REFERENCES file_versions(file_version_id),

    CONSTRAINT ingestion_targets_interface_fk
        FOREIGN KEY (interface_id)
        REFERENCES sensor_file_interfaces(interface_id)
);


CREATE INDEX ingestion_targets_file_version_id_idx
    ON ingestion_targets(file_version_id);


CREATE INDEX ingestion_targets_interface_id_idx
    ON ingestion_targets(interface_id);
