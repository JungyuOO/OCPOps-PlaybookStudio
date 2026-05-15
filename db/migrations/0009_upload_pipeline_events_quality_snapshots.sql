CREATE TABLE IF NOT EXISTS upload_pipeline_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id text NOT NULL,
    event_id text NOT NULL,
    document_source_id uuid REFERENCES document_sources(id) ON DELETE SET NULL,
    parsed_document_id uuid REFERENCES parsed_documents(id) ON DELETE SET NULL,
    stage text NOT NULL,
    event text NOT NULL,
    status text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_upload_pipeline_events_run
    ON upload_pipeline_events(run_id, occurred_at ASC);

CREATE INDEX IF NOT EXISTS idx_upload_pipeline_events_document
    ON upload_pipeline_events(document_source_id, occurred_at ASC);

CREATE INDEX IF NOT EXISTS idx_upload_pipeline_events_parsed_document
    ON upload_pipeline_events(parsed_document_id, occurred_at ASC);

CREATE TABLE IF NOT EXISTS document_quality_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_source_id uuid NOT NULL REFERENCES document_sources(id) ON DELETE CASCADE,
    parsed_document_id uuid NOT NULL REFERENCES parsed_documents(id) ON DELETE CASCADE,
    schema_version text NOT NULL,
    state text NOT NULL,
    score double precision NOT NULL DEFAULT 0,
    checks jsonb NOT NULL DEFAULT '[]'::jsonb,
    blockers jsonb NOT NULL DEFAULT '[]'::jsonb,
    warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_source_id, parsed_document_id, schema_version)
);

CREATE INDEX IF NOT EXISTS idx_document_quality_snapshots_state
    ON document_quality_snapshots(state, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_document_quality_snapshots_document
    ON document_quality_snapshots(document_source_id, updated_at DESC);
