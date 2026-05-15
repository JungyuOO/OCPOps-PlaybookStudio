# Wiki Assets

This folder contains generated official wiki figure/image assets.

## Current Role

These assets are useful evidence, but they are not fully joined into the official
Gold retrieval chunks yet.

Future official Wiki Gold packages should copy or reference these assets through
chunk asset IDs, document assets, and relation/topology records.

## v0.1.4 Caveat

Assets must become `document_assets` and then `image_ref` segments or cited
evidence. A PNG existing here is not enough. The dry-run must show:

```text
asset file -> document_assets -> corpus_chunk_segments.asset_id -> Reader/Chat evidence
```
