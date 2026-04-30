CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS tenants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text NOT NULL UNIQUE,
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS workspaces (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    slug text NOT NULL,
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, slug)
);

CREATE TABLE IF NOT EXISTS document_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES tenants(id) ON DELETE SET NULL,
    workspace_id uuid REFERENCES workspaces(id) ON DELETE SET NULL,
    source_kind text NOT NULL DEFAULT 'upload',
    filename text NOT NULL,
    mime_type text NOT NULL DEFAULT '',
    sha256 text NOT NULL,
    storage_key text NOT NULL,
    byte_size bigint NOT NULL DEFAULT 0,
    access_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, sha256)
);

CREATE TABLE IF NOT EXISTS document_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_source_id uuid NOT NULL REFERENCES document_sources(id) ON DELETE CASCADE,
    version_no integer NOT NULL,
    source_sha256 text NOT NULL,
    storage_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_source_id, version_no)
);

CREATE TABLE IF NOT EXISTS parse_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_source_id uuid NOT NULL REFERENCES document_sources(id) ON DELETE CASCADE,
    document_version_id uuid REFERENCES document_versions(id) ON DELETE SET NULL,
    parser_name text NOT NULL,
    parser_version text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'queued',
    error_code text NOT NULL DEFAULT '',
    error_message text NOT NULL DEFAULT '',
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS parsed_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_source_id uuid NOT NULL REFERENCES document_sources(id) ON DELETE CASCADE,
    document_version_id uuid REFERENCES document_versions(id) ON DELETE SET NULL,
    parse_job_id uuid REFERENCES parse_jobs(id) ON DELETE SET NULL,
    parser_name text NOT NULL,
    parser_version text NOT NULL DEFAULT '',
    title text NOT NULL DEFAULT '',
    markdown text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    outline jsonb NOT NULL DEFAULT '[]'::jsonb,
    warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_blocks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parsed_document_id uuid NOT NULL REFERENCES parsed_documents(id) ON DELETE CASCADE,
    ordinal integer NOT NULL,
    block_type text NOT NULL,
    heading_level integer,
    page_number integer,
    text text NOT NULL DEFAULT '',
    markdown text NOT NULL DEFAULT '',
    section_path jsonb NOT NULL DEFAULT '[]'::jsonb,
    bbox jsonb NOT NULL DEFAULT '{}'::jsonb,
    table_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (parsed_document_id, ordinal)
);

CREATE TABLE IF NOT EXISTS document_assets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_source_id uuid NOT NULL REFERENCES document_sources(id) ON DELETE CASCADE,
    parsed_document_id uuid REFERENCES parsed_documents(id) ON DELETE CASCADE,
    block_id uuid REFERENCES document_blocks(id) ON DELETE SET NULL,
    asset_type text NOT NULL DEFAULT 'image',
    mime_type text NOT NULL DEFAULT '',
    storage_key text NOT NULL,
    sha256 text NOT NULL,
    width integer,
    height integer,
    page_number integer,
    bbox jsonb NOT NULL DEFAULT '{}'::jsonb,
    caption_text text NOT NULL DEFAULT '',
    ocr_text text NOT NULL DEFAULT '',
    qwen_description text NOT NULL DEFAULT '',
    qwen_model text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parsed_document_id uuid NOT NULL REFERENCES parsed_documents(id) ON DELETE CASCADE,
    chunk_key text NOT NULL,
    ordinal integer NOT NULL,
    chunk_type text NOT NULL DEFAULT 'document',
    markdown text NOT NULL,
    embedding_text text NOT NULL,
    token_count integer NOT NULL DEFAULT 0,
    page_start integer,
    page_end integer,
    section_path jsonb NOT NULL DEFAULT '[]'::jsonb,
    asset_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (parsed_document_id, chunk_key)
);

CREATE TABLE IF NOT EXISTS embedding_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id uuid NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
    model text NOT NULL,
    status text NOT NULL DEFAULT 'queued',
    error_message text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

CREATE TABLE IF NOT EXISTS qdrant_index_entries (
    chunk_id uuid NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
    collection text NOT NULL,
    point_id text NOT NULL,
    vector_model text NOT NULL,
    payload_hash text NOT NULL,
    indexed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (chunk_id, collection)
);

CREATE TABLE IF NOT EXISTS question_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES tenants(id) ON DELETE SET NULL,
    workspace_id uuid REFERENCES workspaces(id) ON DELETE SET NULL,
    session_id text NOT NULL DEFAULT '',
    user_query text NOT NULL,
    rewritten_query text NOT NULL DEFAULT '',
    retrieved_chunk_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    no_answer_reason text NOT NULL DEFAULT '',
    quality_signal jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS answer_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    question_log_id uuid REFERENCES question_logs(id) ON DELETE SET NULL,
    answer text NOT NULL,
    cited_chunk_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    cited_asset_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    retrieval_trace jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_document_sources_workspace_created
    ON document_sources(workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_document_blocks_parsed_type
    ON document_blocks(parsed_document_id, block_type, ordinal);

CREATE INDEX IF NOT EXISTS idx_document_chunks_parsed_ordinal
    ON document_chunks(parsed_document_id, ordinal);

CREATE INDEX IF NOT EXISTS idx_parse_jobs_status_created
    ON parse_jobs(status, created_at);

CREATE INDEX IF NOT EXISTS idx_embedding_jobs_status_created
    ON embedding_jobs(status, created_at);
