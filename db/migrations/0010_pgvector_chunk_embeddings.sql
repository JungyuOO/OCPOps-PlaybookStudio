CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id uuid NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
    model text NOT NULL,
    embedding vector(1024) NOT NULL,
    embedding_text_hash text NOT NULL,
    payload_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (chunk_id, model)
);

CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_model
    ON chunk_embeddings(model);

CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_text_hash
    ON chunk_embeddings(model, embedding_text_hash);

CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_embedding_hnsw
    ON chunk_embeddings
    USING hnsw (embedding vector_cosine_ops);
