CREATE TABLE IF NOT EXISTS course_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_slug TEXT NOT NULL DEFAULT 'project-playbook',
    asset_key TEXT NOT NULL,
    asset_path TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    byte_size INTEGER NOT NULL DEFAULT 0,
    checksum TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    content BYTEA NOT NULL,
    source_ref TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (course_slug, asset_key),
    UNIQUE (course_slug, asset_path)
);

CREATE INDEX IF NOT EXISTS idx_course_assets_course_path
    ON course_assets (course_slug, asset_path);

CREATE INDEX IF NOT EXISTS idx_course_assets_updated_at
    ON course_assets (updated_at DESC);
