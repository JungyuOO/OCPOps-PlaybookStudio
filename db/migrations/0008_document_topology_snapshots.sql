CREATE TABLE IF NOT EXISTS document_topology_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_source_id uuid NOT NULL REFERENCES document_sources(id) ON DELETE CASCADE,
    document_version_id uuid REFERENCES document_versions(id) ON DELETE SET NULL,
    parsed_document_id uuid NOT NULL REFERENCES parsed_documents(id) ON DELETE CASCADE,
    schema_version text NOT NULL,
    source_fingerprint text NOT NULL,
    input_fingerprint text NOT NULL,
    state text NOT NULL DEFAULT '',
    partial boolean NOT NULL DEFAULT false,
    node_count integer NOT NULL DEFAULT 0,
    edge_count integer NOT NULL DEFAULT 0,
    topology jsonb NOT NULL DEFAULT '{}'::jsonb,
    summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    nodes jsonb NOT NULL DEFAULT '[]'::jsonb,
    edges jsonb NOT NULL DEFAULT '[]'::jsonb,
    blockers jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    UNIQUE (document_source_id, parsed_document_id, schema_version),
    UNIQUE (parsed_document_id, schema_version, input_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_document_topology_source_schema
    ON document_topology_snapshots(document_source_id, schema_version, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_document_topology_source_fingerprint_schema
    ON document_topology_snapshots(source_fingerprint, schema_version);

CREATE INDEX IF NOT EXISTS idx_document_topology_state_updated
    ON document_topology_snapshots(state, updated_at DESC);
