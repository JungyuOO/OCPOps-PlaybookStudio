CREATE TABLE IF NOT EXISTS graph_entities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_kind text NOT NULL,
    name text NOT NULL,
    display_name text NOT NULL DEFAULT '',
    entity_key text NOT NULL,
    aliases jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_scope text NOT NULL DEFAULT 'user_upload',
    owner_user_id text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    mention_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_entities_key_scope
    ON graph_entities(entity_key, source_scope, owner_user_id);

CREATE INDEX IF NOT EXISTS idx_graph_entities_name
    ON graph_entities(name);

CREATE INDEX IF NOT EXISTS idx_graph_entities_kind
    ON graph_entities(entity_kind);

CREATE TABLE IF NOT EXISTS graph_entity_mentions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id uuid NOT NULL REFERENCES graph_entities(id) ON DELETE CASCADE,
    source_kind text NOT NULL DEFAULT 'chunk',
    chunk_id uuid NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
    source_ref text NOT NULL DEFAULT '',
    document_source_id uuid NULL REFERENCES document_sources(id) ON DELETE CASCADE,
    parsed_document_id uuid NULL,
    quote text NOT NULL DEFAULT '',
    quote_sha256 text NOT NULL DEFAULT '',
    locator jsonb NOT NULL DEFAULT '{}'::jsonb,
    extraction_method text NOT NULL DEFAULT 'rule',
    extractor_version text NOT NULL DEFAULT 'rule-v1',
    confidence real NOT NULL DEFAULT 1.0,
    source_scope text NOT NULL DEFAULT 'user_upload',
    repository_id uuid NULL,
    owner_user_id text NOT NULL DEFAULT '',
    visibility text NOT NULL DEFAULT 'workspace_shared',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT graph_entity_mentions_source_check CHECK (
        (source_kind = 'chunk' AND chunk_id IS NOT NULL)
        OR (source_kind <> 'chunk' AND chunk_id IS NULL AND source_ref <> '')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_entity_mentions_dedup
    ON graph_entity_mentions(
        entity_id,
        source_kind,
        COALESCE(chunk_id, '00000000-0000-0000-0000-000000000000'::uuid),
        source_ref,
        quote_sha256
    );

CREATE INDEX IF NOT EXISTS idx_graph_entity_mentions_chunk
    ON graph_entity_mentions(chunk_id);

CREATE INDEX IF NOT EXISTS idx_graph_entity_mentions_entity
    ON graph_entity_mentions(entity_id);

CREATE INDEX IF NOT EXISTS idx_graph_entity_mentions_document_source
    ON graph_entity_mentions(document_source_id);

CREATE INDEX IF NOT EXISTS idx_graph_entity_mentions_scope
    ON graph_entity_mentions(source_scope, owner_user_id, visibility);

CREATE TABLE IF NOT EXISTS graph_entity_relations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_entity_id uuid NOT NULL REFERENCES graph_entities(id) ON DELETE CASCADE,
    object_entity_id uuid NOT NULL REFERENCES graph_entities(id) ON DELETE CASCADE,
    relation_type text NOT NULL,
    source_kind text NOT NULL DEFAULT 'chunk',
    chunk_id uuid NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
    source_ref text NOT NULL DEFAULT '',
    document_source_id uuid NULL REFERENCES document_sources(id) ON DELETE CASCADE,
    quote text NOT NULL DEFAULT '',
    quote_sha256 text NOT NULL DEFAULT '',
    locator jsonb NOT NULL DEFAULT '{}'::jsonb,
    extraction_method text NOT NULL DEFAULT 'rule',
    extractor_version text NOT NULL DEFAULT 'rule-v1',
    confidence real NOT NULL DEFAULT 1.0,
    source_scope text NOT NULL DEFAULT 'user_upload',
    repository_id uuid NULL,
    owner_user_id text NOT NULL DEFAULT '',
    visibility text NOT NULL DEFAULT 'workspace_shared',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT graph_entity_relations_source_check CHECK (
        (source_kind = 'chunk' AND chunk_id IS NOT NULL)
        OR (source_kind <> 'chunk' AND chunk_id IS NULL AND source_ref <> '')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_entity_relations_dedup
    ON graph_entity_relations(
        subject_entity_id,
        object_entity_id,
        relation_type,
        source_kind,
        COALESCE(chunk_id, '00000000-0000-0000-0000-000000000000'::uuid),
        source_ref
    );

CREATE INDEX IF NOT EXISTS idx_graph_entity_relations_subject
    ON graph_entity_relations(subject_entity_id);

CREATE INDEX IF NOT EXISTS idx_graph_entity_relations_object
    ON graph_entity_relations(object_entity_id);

CREATE INDEX IF NOT EXISTS idx_graph_entity_relations_document_source
    ON graph_entity_relations(document_source_id);

CREATE INDEX IF NOT EXISTS idx_graph_entity_relations_scope
    ON graph_entity_relations(source_scope, owner_user_id, visibility);
