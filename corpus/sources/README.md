# Corpus Sources

`sources/` contains packages that can be imported or rebuilt into the runtime
database.

In v0.1.4 terms, this folder feeds the `document_sources` / parsing layer. It
does not replace the runtime corpus tables.

## Subfolders

| Folder | Meaning | Current state |
| --- | --- | --- |
| `official/` | OpenShift official documentation seeds and source-first rebuild candidates | still has legacy `imported-gold/` naming |
| `kmsc/` | KMSC customer/training packages | contains the clean reference package |

## Clean Reference

Use `kmsc/parsed-preview/course_pbs/` as the current package model:

- package README
- one chunk stream: `chunks.jsonl`
- local evidence assets: `assets/`
- package/control manifests: `manifests/`

The parent name `parsed-preview` is legacy, but the package shape is the clean
one. Do not copy the official `imported-gold/` naming for new packages.

Runtime code should not answer directly from this folder after import. Runtime
truth is PostgreSQL plus Qdrant plus storage.

## Package Requirements

New source packages should include enough evidence to dry-run the v0.1.4 path:

- provenance: where the source came from and which version/branch/hash was used
- parser input: raw file, JSONL, OCR output, or package manifest
- package README: role, owner, import scope, known blocker
- chunk or block evidence: enough to map into `document_blocks`
- asset evidence: images/tables/OCR where applicable
- encoding: UTF-8 text, no silent mojibake

If a package cannot explain how it becomes `document_sources -> parsed_documents
-> document_blocks/assets`, it is not ready to be treated as a stable source
package.
