# Wiki Library count mismatch follow-up

Date: 2026-05-15

## Issue

Question received:

> 레포에는 데이터가 29개라는데 왜 페이지에는 34권으로 뜨나요?

## Current Interpretation

This is not a data increase. It is a count/label mismatch.

- `29` means official source/runtime documents.
- `34` is likely an operational wiki output aggregate:
  - `Gold Ready`: 23
  - `Gold Recovery / repair needed`: 11
  - Total visible operational wiki output: 34

The problem is that the UI can make these look like the same unit, even though they are different concepts.

## Evidence Checked

Current runtime/API evidence:

- PostgreSQL `document_sources`
  - `official_docs`: 29
  - `study_docs`: 9
  - `user_upload`: 10
- `corpus/data/wiki_runtime_books/active_manifest.json`
  - `runtime_count`: 29
- `/api/repositories/documents`
  - Official Docs `document_count`: 29
  - Study Docs `document_count`: 9
- `/api/repositories/official-catalog`
  - `live_count`: 29
  - `candidate_count`: 84
  - `total_count`: 113
- `/api/data-control-room` summary
  - `approved_runtime_count`: 29
  - `corpus_book_count`: 29
  - `manualbook_count`: 29
  - `db_official_document_count`: 29
  - `gold_book_count`: 23
  - `approved_wiki_runtime_book_count`: 23
  - `gold_recovery_count`: 11

## Product Meaning

The UI should not use one vague label like `books` or `권` for all of these.

Recommended labels:

- `공식 원천 문서`: 29개
- `Gold Ready`: 23권
- `수리 필요`: 11건
- `공식 후보`: 84개
- `전체 공식 카탈로그`: 113개

## Fix Direction

Later task:

1. Audit `PlaybookLibraryPage.tsx` count labels around operational wiki/detail sections.
2. Make each count show its source and unit.
3. Do not show `23 + 11 = 34` as if it were official repository document count.
4. If both numbers are shown near each other, add a small breakdown:
   - `공식 문서 29개`
   - `Gold 23권`
   - `수리 필요 11건`
5. Keep source catalog count separate:
   - `공식 카탈로그 113개 = 준비됨 29 + 후보 84`

## Acceptance

- A user can answer: "왜 29와 34가 다른가?"
- The first viewport does not imply that official source documents are 34.
- `Document`, `Book`, `Gold`, `Recovery`, `Candidate` are not used interchangeably.
- The count source can be traced to an API field or DB query.
