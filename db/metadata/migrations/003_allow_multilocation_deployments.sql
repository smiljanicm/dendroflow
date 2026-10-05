-- One physical sensor may measure the same variable at distinct locations
-- simultaneously (for example, a SoilVue10 at several soil depths).
ALTER TABLE deployments
    DROP CONSTRAINT deployments_no_overlap;

ALTER TABLE deployments
    ADD CONSTRAINT deployments_no_overlap
        EXCLUDE USING gist (
            sensor_id WITH =,
            location_id WITH =,
            variable_id WITH =,
            tstzrange(valid_from, valid_to, '[)') WITH &&
        );
