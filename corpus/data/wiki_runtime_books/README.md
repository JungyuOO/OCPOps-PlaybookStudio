# Wiki Runtime Book Manifests

This folder contains transitional active/full rebuild manifests for wiki runtime
books.

## Caveat

Some paths in these manifests can point to older absolute workspaces. Treat this
folder as rebuild evidence only until a fresh audit confirms the paths and source
truth.

Runtime answers should come from PostgreSQL/Qdrant/storage, not directly from
this folder.

## v0.1.4 Caveat

These manifests can help explain why a page once showed a runtime count, but
they do not prove current corpus freshness. If `embedding_text` or Qdrant payload
shape changes, these manifests are only historical evidence; PostgreSQL/Qdrant
checks decide the current runtime state.
