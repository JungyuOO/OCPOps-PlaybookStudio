CREATE TABLE IF NOT EXISTS chat_feedback_issues (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES tenants(id) ON DELETE SET NULL,
    workspace_id uuid REFERENCES workspaces(id) ON DELETE SET NULL,
    owner_user_id text NOT NULL DEFAULT '',
    user_id text NOT NULL DEFAULT '',
    client_session_id text NOT NULL DEFAULT '',
    user_message_id uuid REFERENCES chat_messages(id) ON DELETE SET NULL,
    assistant_message_id uuid REFERENCES chat_messages(id) ON DELETE SET NULL,
    status text NOT NULL DEFAULT 'open',
    issue_type text NOT NULL,
    severity text NOT NULL DEFAULT 'medium',
    gap_type text NOT NULL DEFAULT 'unclassified',
    user_query text NOT NULL,
    assistant_answer text NOT NULL,
    user_comment text NOT NULL DEFAULT '',
    expected_answer text NOT NULL DEFAULT '',
    active_repository_id uuid REFERENCES repositories(id) ON DELETE SET NULL,
    active_document_id uuid REFERENCES document_sources(id) ON DELETE SET NULL,
    cited_chunk_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    cited_asset_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    citations jsonb NOT NULL DEFAULT '[]'::jsonb,
    retrieval_trace jsonb NOT NULL DEFAULT '{}'::jsonb,
    pipeline_trace jsonb NOT NULL DEFAULT '{}'::jsonb,
    qwen_draft jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_feedback_status_created
    ON chat_feedback_issues(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_feedback_owner_created
    ON chat_feedback_issues(owner_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_feedback_gap_type
    ON chat_feedback_issues(gap_type, created_at DESC);
