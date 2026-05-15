# Corpus Data Sidecars

This folder contains transitional wiki sidecars and generated support data.

These files are evidence and compatibility sidecars. They are not the v0.1.4
corpus truth and should not be used as the only proof that Reader, Chat, Qdrant,
or Gold are healthy.

## Subfolders

- `wiki_assets/`: source-first wiki figure/image assets.
- `wiki_relations/`: relation indexes that connect figures, sections, and
  entities.
- `wiki_runtime_books/`: transitional active/full rebuild manifests. Some paths
  may be stale and should not be treated as runtime truth without audit.

New source packages should prefer `corpus/sources/...` instead of adding more
data here.

## v0.1.4 Rule

- If a sidecar is still needed, document which runtime/API still reads it.
- If a sidecar is only historical evidence, keep it out of new import paths.
- If Qdrant payload or `embedding_text` changes, sidecar manifests do not prove
  freshness; rebuild evidence must come from PostgreSQL/Qdrant checks.
