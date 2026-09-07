CREATE TABLE ingestion_batches (
    ingestion_batch_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    ingestion_run_id BIGINT NOT NULL,
    file_version_id BIGINT NOT NULL,

    batch_number BIGINT NOT NULL,

    source_line_start BIGINT NOT NULL,
    source_line_end BIGINT NOT NULL,
    row_count BIGINT NOT NULL,

    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,

    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,

    error_message TEXT,

    CONSTRAINT ingestion_batches_run_fk
        FOREIGN KEY (ingestion_run_id)
        REFERENCES ingestion_runs(ingestion_run_id),

    CONSTRAINT ingestion_batches_version_fk
        FOREIGN KEY (file_version_id)
        REFERENCES file_versions(file_version_id),

    CONSTRAINT ingestion_batches_run_version_batch_unique
        UNIQUE (
            ingestion_run_id,
            file_version_id,
            batch_number
        ),

    CONSTRAINT ingestion_batches_batch_number_check
        CHECK (batch_number > 0),

    CONSTRAINT ingestion_batches_source_line_check
        CHECK (
            source_line_start > 0
            AND source_line_end >= source_line_start
        ),

    CONSTRAINT ingestion_batches_row_count_check
        CHECK (
            row_count > 0
            AND row_count <= source_line_end - source_line_start + 1
        ),

    CONSTRAINT ingestion_batches_status_check
        CHECK (
            status IN (
                'pending',
                'running',
                'completed',
                'failed'
            )
        ),

    CONSTRAINT ingestion_batches_attempt_count_check
        CHECK (attempt_count >= 0),

    CONSTRAINT ingestion_batches_finished_check
        CHECK (
            finished_at IS NULL
            OR (
                started_at IS NOT NULL
                AND finished_at >= started_at
            )
        ),

    CONSTRAINT ingestion_batches_state_check
        CHECK (
            (
                status = 'pending'
                AND started_at IS NULL
                AND finished_at IS NULL
            )
            OR
            (
                status = 'running'
                AND started_at IS NOT NULL
                AND finished_at IS NULL
            )
            OR
            (
                status IN ('completed', 'failed')
                AND started_at IS NOT NULL
                AND finished_at IS NOT NULL
            )
        )
);


CREATE INDEX ingestion_batches_run_id_idx
    ON ingestion_batches(ingestion_run_id);


CREATE INDEX ingestion_batches_file_version_id_idx
    ON ingestion_batches(file_version_id);


CREATE INDEX ingestion_batches_status_idx
    ON ingestion_batches(status);
