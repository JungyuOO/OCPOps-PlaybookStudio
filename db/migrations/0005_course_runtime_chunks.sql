CREATE TABLE IF NOT EXISTS course_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_slug TEXT NOT NULL DEFAULT 'project-playbook',
    chunk_key TEXT NOT NULL,
    stage_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    search_text TEXT NOT NULL DEFAULT '',
    source_ref TEXT NOT NULL DEFAULT '',
    checksum TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (course_slug, chunk_key)
);

CREATE INDEX IF NOT EXISTS idx_course_chunks_course_stage
    ON course_chunks (course_slug, stage_id, chunk_key);

CREATE INDEX IF NOT EXISTS idx_course_chunks_updated_at
    ON course_chunks (updated_at DESC);
