ALTER TABLE location_types
RENAME COLUMN name TO type;

ALTER TABLE location_types
RENAME CONSTRAINT location_types_name_key
TO location_types_type_key;
