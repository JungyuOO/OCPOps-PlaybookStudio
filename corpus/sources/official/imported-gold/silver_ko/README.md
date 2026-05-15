# Official Korean Silver Drafts

This folder contains translation and normalization intermediates.

## Contents

- `translation_drafts/`: draft translated chunks, documents, playbooks, and cache.

## Role

Use this for translation review, terminology recovery, and rebuild evidence. Do
not treat these drafts as final official Gold without approval and quality gates.

## v0.1.4 Caveat

Silver draft data can help recover source wording and terminology, but it is not
the corpus truth. Before it can become answer-ready corpus, it must pass through:

```text
parsed_documents -> document_blocks/assets -> corpus segments/commands/refs
```

Translation cache files must also preserve UTF-8 text and avoid silent mojibake.
