CREATE TABLE clean_datasets (
    clean_dataset_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    name TEXT NOT NULL,
    description JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT clean_datasets_name_unique
        UNIQUE (name)
);


CREATE TABLE quality_flags (
    quality_flag_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    code TEXT NOT NULL,
    description TEXT,

    CONSTRAINT quality_flags_code_unique
        UNIQUE (code)
);


CREATE TABLE clean_observations (
    clean_observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    clean_dataset_id BIGINT NOT NULL,
    location_id BIGINT NOT NULL,
    variable_id BIGINT NOT NULL,

    timestamp TIMESTAMPTZ NOT NULL,
    value DOUBLE PRECISION NOT NULL,

    quality_status TEXT NOT NULL,

    CONSTRAINT clean_observations_dataset_fk
        FOREIGN KEY (clean_dataset_id)
        REFERENCES clean_datasets(clean_dataset_id),

    CONSTRAINT clean_observations_quality_status_check
        CHECK (quality_status IN ('valid', 'suspect', 'invalid')),

    CONSTRAINT clean_observations_identity_unique
        UNIQUE (clean_dataset_id, location_id, variable_id, timestamp)
);


CREATE TABLE clean_observation_inputs (
    clean_observation_id BIGINT NOT NULL,
    raw_observation_id BIGINT NOT NULL,

    CONSTRAINT clean_observation_inputs_pkey
        PRIMARY KEY (clean_observation_id, raw_observation_id),

    CONSTRAINT clean_observation_inputs_clean_fk
        FOREIGN KEY (clean_observation_id)
        REFERENCES clean_observations(clean_observation_id)
);


CREATE TABLE clean_observation_quality (
    clean_observation_id BIGINT NOT NULL,
    quality_flag_id BIGINT NOT NULL,

    CONSTRAINT clean_observation_quality_pkey
        PRIMARY KEY (clean_observation_id, quality_flag_id),

    CONSTRAINT clean_observation_quality_clean_fk
        FOREIGN KEY (clean_observation_id)
        REFERENCES clean_observations(clean_observation_id),

    CONSTRAINT clean_observation_quality_flag_fk
        FOREIGN KEY (quality_flag_id)
        REFERENCES quality_flags(quality_flag_id)
);

