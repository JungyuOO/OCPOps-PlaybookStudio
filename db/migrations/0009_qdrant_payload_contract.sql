ALTER TABLE qdrant_index_entries
    ADD COLUMN IF NOT EXISTS payload_version integer NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_qdrant_index_entries_payload_version
    ON qdrant_index_entries(collection, payload_version);
