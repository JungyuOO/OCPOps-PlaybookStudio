ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS chunk_role text NOT NULL DEFAULT 'leaf',
    ADD COLUMN IF NOT EXISTS parent_chunk_id uuid NULL REFERENCES document_chunks(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS child_chunk_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS navigation_only boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS beginner_narrative text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS starter_question_candidates jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS followup_question_candidates jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS question_candidates_version integer NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_document_chunks_navigation_enabled
    ON document_chunks(source_scope, repository_id, ordinal)
    WHERE navigation_only = false;

CREATE INDEX IF NOT EXISTS idx_document_chunks_parent_chunk
    ON document_chunks(parent_chunk_id)
    WHERE parent_chunk_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_document_chunks_chunk_role
    ON document_chunks(chunk_role);
