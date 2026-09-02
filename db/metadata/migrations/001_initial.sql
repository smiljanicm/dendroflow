CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE sites (
    site_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    parent_id BIGINT,
    site_code TEXT NOT NULL UNIQUE,

    CONSTRAINT sites_latitude_check
        CHECK (latitude BETWEEN -90 AND 90),

    CONSTRAINT sites_longitude_check
        CHECK (longitude BETWEEN -180 AND 180),

    CONSTRAINT sites_parent_fk
        FOREIGN KEY (parent_id)
        REFERENCES sites(site_id)
);

CREATE TABLE location_types (
    location_type_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE locations (
    location_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    site_id BIGINT NOT NULL,
    location_type_id BIGINT NOT NULL,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    height_above_ground DOUBLE PRECISION,
    azimuth DOUBLE PRECISION,

    CONSTRAINT locations_site_fk
        FOREIGN KEY (site_id)
        REFERENCES sites(site_id),

    CONSTRAINT locations_type_fk
        FOREIGN KEY (location_type_id)
        REFERENCES location_types(location_type_id),

    CONSTRAINT locations_latitude_check
        CHECK (latitude BETWEEN -90 AND 90),

    CONSTRAINT locations_longitude_check
        CHECK (longitude BETWEEN -180 AND 180),

    CONSTRAINT locations_azimuth_check
        CHECK (azimuth >= 0 AND azimuth < 360),

    CONSTRAINT locations_coordinates_check
        CHECK (
            (latitude IS NULL AND longitude IS NULL)
            OR
            (latitude IS NOT NULL AND longitude IS NOT NULL)
        )
);

CREATE INDEX locations_site_id_idx
    ON locations(site_id);

CREATE INDEX locations_location_type_id_idx
    ON locations(location_type_id);

CREATE TABLE location_labels (
    location_label_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_id BIGINT NOT NULL,
    label TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,

    CONSTRAINT location_labels_location_fk
        FOREIGN KEY (location_id)
        REFERENCES locations(location_id),

    CONSTRAINT location_labels_validity_check
        CHECK (valid_to IS NULL OR valid_to > valid_from),

    CONSTRAINT location_labels_no_overlap
        EXCLUDE USING gist (
            location_id WITH =,
            tstzrange(valid_from, valid_to, '[)') WITH &&
        )
);

CREATE TABLE sensor_types (
    sensor_type_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE sensor_models (
    sensor_model_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model TEXT NOT NULL,
    manufacturer TEXT,
    sensor_type_id BIGINT NOT NULL,

    CONSTRAINT sensor_models_sensor_type_fk
        FOREIGN KEY (sensor_type_id)
        REFERENCES sensor_types(sensor_type_id),

    CONSTRAINT sensor_models_manufacturer_model_unique
        UNIQUE (manufacturer, model)
);

CREATE TABLE sensors (
    sensor_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_model_id BIGINT NOT NULL,
    serial_number TEXT NOT NULL,
    description TEXT,

    CONSTRAINT sensors_sensor_model_fk
        FOREIGN KEY (sensor_model_id)
        REFERENCES sensor_models(sensor_model_id),

    CONSTRAINT sensors_model_serial_unique
        UNIQUE (sensor_model_id, serial_number)
);

CREATE TABLE variables (
    variable_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    variable TEXT NOT NULL UNIQUE,
    derived BOOLEAN NOT NULL DEFAULT FALSE,
    description TEXT
);

CREATE TABLE deployments (
    deployment_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_id BIGINT NOT NULL,
    location_id BIGINT NOT NULL,
    variable_id BIGINT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,

    CONSTRAINT deployments_sensor_fk
        FOREIGN KEY (sensor_id)
        REFERENCES sensors(sensor_id),

    CONSTRAINT deployments_location_fk
        FOREIGN KEY (location_id)
        REFERENCES locations(location_id),

    CONSTRAINT deployments_variable_fk
        FOREIGN KEY (variable_id)
        REFERENCES variables(variable_id),

    CONSTRAINT deployments_validity_check
        CHECK (valid_to IS NULL OR valid_to > valid_from),

    CONSTRAINT deployments_no_overlap
        EXCLUDE USING gist (
            sensor_id WITH =,
            variable_id WITH =,
            tstzrange(valid_from, valid_to, '[)') WITH &&
        )
);

