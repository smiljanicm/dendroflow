ALTER TABLE files
ADD COLUMN reader_config JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE files
ADD CONSTRAINT files_reader_config_object_check
CHECK (jsonb_typeof(reader_config) = 'object');
