# Official Korean Manualbook Artifacts

This folder contains generated official manualbook/playbook-style documents.

## Files

- `playbook_documents.jsonl`: document-level manualbook records.
- `playbooks/`: one JSON file per generated book.

## Role

Use this as a generated reading/book artifact seed. It is adjacent to the
retrieval corpus, not a complete source-first package by itself.

## v0.1.4 Caveat

Manualbook artifacts are display/reading artifacts. They do not replace:

- parsing blocks/assets
- corpus segments/commands/refs/question candidates
- Qdrant projection checks
- Reader/Chat runtime validation

Use these files as historical viewer/book evidence, not as proof that the
official corpus is answer-ready.
