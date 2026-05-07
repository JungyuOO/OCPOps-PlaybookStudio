CREATE TABLE IF NOT EXISTS course_manifests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_slug TEXT NOT NULL DEFAULT 'project-playbook',
    manifest_key TEXT NOT NULL DEFAULT 'course_v1',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    stage_count INTEGER NOT NULL DEFAULT 0,
    stop_count INTEGER NOT NULL DEFAULT 0,
    source_ref TEXT NOT NULL DEFAULT '',
    checksum TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (course_slug, manifest_key)
);

CREATE INDEX IF NOT EXISTS idx_course_manifests_updated_at
    ON course_manifests (updated_at DESC);
