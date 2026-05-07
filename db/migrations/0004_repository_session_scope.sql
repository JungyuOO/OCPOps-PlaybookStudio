CREATE TABLE IF NOT EXISTS repositories (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES tenants(id) ON DELETE SET NULL,
    workspace_id uuid REFERENCES workspaces(id) ON DELETE SET NULL,
    owner_user_id text NOT NULL DEFAULT '',
    slug text NOT NULL,
    title text NOT NULL,
    repository_kind text NOT NULL DEFAULT 'personal',
    visibility text NOT NULL DEFAULT 'private_user',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_repositories_scope_slug
    ON repositories (
        COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid),
        COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid),
        owner_user_id,
        slug
    );

ALTER TABLE document_sources
    ADD COLUMN IF NOT EXISTS repository_id uuid REFERENCES repositories(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS owner_user_id text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS visibility text NOT NULL DEFAULT 'workspace_shared',
    ADD COLUMN IF NOT EXISTS source_scope text NOT NULL DEFAULT 'user_upload';

ALTER TABLE document_blocks
    ADD COLUMN IF NOT EXISTS section_number text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS heading_title text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS source_anchor text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS toc_path jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS section_number text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS heading_title text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS source_anchor text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS toc_path jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS repository_id uuid REFERENCES repositories(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS owner_user_id text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS visibility text NOT NULL DEFAULT 'workspace_shared',
    ADD COLUMN IF NOT EXISTS source_scope text NOT NULL DEFAULT 'user_upload';

CREATE TABLE IF NOT EXISTS chat_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES tenants(id) ON DELETE SET NULL,
    workspace_id uuid REFERENCES workspaces(id) ON DELETE SET NULL,
    anonymous_user_id text NOT NULL DEFAULT '',
    user_id text NOT NULL DEFAULT '',
    client_session_id text NOT NULL,
    active_repository_id uuid REFERENCES repositories(id) ON DELETE SET NULL,
    title text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'active',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_session_id uuid NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role text NOT NULL,
    content text NOT NULL,
    cited_chunk_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    cited_asset_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_document_sources_repository_created
    ON document_sources(repository_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_document_sources_visibility_owner
    ON document_sources(visibility, owner_user_id, source_scope);

CREATE INDEX IF NOT EXISTS idx_document_chunks_repository_scope
    ON document_chunks(repository_id, visibility, owner_user_id, source_scope);

CREATE INDEX IF NOT EXISTS idx_document_chunks_source_anchor
    ON document_chunks(source_anchor);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_owner_updated
    ON chat_sessions(workspace_id, anonymous_user_id, user_id, updated_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_sessions_scope_client
    ON chat_sessions (
        COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid),
        anonymous_user_id,
        user_id,
        client_session_id
    );

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
    ON chat_messages(chat_session_id, created_at);
