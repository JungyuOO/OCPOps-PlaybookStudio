# Corpus Seed Area

`corpus/`는 런타임 DB가 아니라 **원천/패키지/평가 근거를 두는 작업장**이다.
앱이 실제로 답변할 때의 truth는 PostgreSQL, Qdrant, runtime storage다.

v0.1.4 기준으로 이 폴더는 `Parsing`과 `Corpus`를 만들기 전의
source/import/evidence 영역이다. 여기 있는 JSON/JSONL/MD 파일이 곧바로
제품 Gold나 챗봇 truth가 되지는 않는다.

## 한눈에 보는 결론

| Folder | 역할 | 지금 판단 |
| --- | --- | --- |
| `sources/` | import 가능한 source/corpus package | 핵심 작업 공간 |
| `manifests/` | 무엇을 가져오고 평가할지 정하는 control plane | 유지 |
| `data/` | 예전 wiki sidecar와 rebuild evidence | transitional, 신규 작업은 가급적 금지 |

## v0.1.4 Boundary

```text
corpus/sources + corpus/manifests + corpus/data evidence
  -> Parsing layer: 원본/파서가 본 구조 보존
  -> Corpus layer: 검색/답변용 truth
  -> Qdrant: corpus에서 재생성 가능한 vector projection
  -> Reader/Chat runtime: PostgreSQL + Qdrant + storage를 사용
```

작업자가 지켜야 할 경계:

- `Parsing`은 원본 보존 계층이다. 검색/답변하지 않는다.
- `Corpus`는 검색/답변 truth다. segment, command, ref, question 후보를 가진다.
- `Qdrant`는 projection이다. corpus만 보고 다시 만들 수 있어야 한다.
- `corpus/` 파일은 seed/import/evidence다. runtime truth라고 보고하지 않는다.

## Text Contract

v0.1.4 dry-run과 이후 migration은 텍스트를 한 덩어리 markdown으로 보지 않는다.

| Layer | Purpose |
| --- | --- |
| `raw_text` | parser가 본 원문 보존 |
| `markdown` | Reader/사람 표시용 |
| `normalized_text` | BM25/정확검색용 정규화 텍스트 |
| `embedding_text` | vector embedding 입력. code fence, 내부 태그, URL, viewer path 제거 |

새 package나 importer는 이 4계층으로 분해 가능한 근거를 남겨야 한다.

## Encoding Rule

- 모든 새 텍스트 산출물은 UTF-8을 명시한다.
- Python 파일 I/O는 `encoding="utf-8"`을 기본으로 한다.
- JSON 생성은 한글을 보존할 수 있게 `ensure_ascii=False`를 사용한다.
- mojibake가 보이면 정제 문제가 아니라 source/parsing 품질 blocker로 기록한다.

가장 참고할 만한 정리된 레퍼런스는
`sources/kmsc/parsed-preview/course_pbs/`다. 이 패키지는 `chunks.jsonl`,
`assets/`, `manifests/`, README가 한 곳에 있어 사람이 보고 이해하기 쉽다.
앞으로 official/user upload도 이 모델을 따라가야 한다.

## Current Layout

```text
corpus/
|-- sources/
|   |-- official/
|   `-- kmsc/
|-- manifests/
|   |-- concepts/
|   |-- course/
|   |-- demo/
|   |-- eval/
|   `-- official/
`-- data/
    |-- wiki_assets/
    |-- wiki_relations/
    `-- wiki_runtime_books/
```

## Reference Package Model

현재 가장 깨끗한 모델:

```text
corpus/sources/kmsc/parsed-preview/course_pbs/
|-- README.md
|-- chunks.jsonl
|-- assets/
`-- manifests/
```

향후 official/source-first package 목표:

```text
corpus/sources/official/<package-name>/
|-- README.md
|-- chunks.jsonl
|-- assets/
|-- manifests/
|-- quality/
`-- handoff/
```

`quality/`와 `handoff/`는 아직 모든 패키지에 있는 현재 구조가 아니다.
목표 구조다. 지금은 KMSC 모델을 기준으로 assets/manifests/chunks를 먼저
한 package 안에 묶는 것이 1차 정리 기준이다.

## Transitional Areas

- `data/wiki_assets` and `data/wiki_relations` are source-first wiki sidecars.
- `data/wiki_runtime_books` is a stale/transitional runtime manifest area and is
  not the DB source of truth.
- `sources/official/imported-gold` is a legacy imported official retrieval seed
  area. The name contains `gold`, but it is not product-level Wiki Gold. Product
  Gold requires readable chunks, source/asset evidence, topology, quality
  snapshots, and runtime import verification.

## Migration Targets

- Keep current code-bound legacy paths until `corpus_paths.py` aliases have
  replaced direct literals and tests prove no runtime/import regressions.
- Future official source-first packages should use the KMSC package shape:
  `chunks.jsonl`, `assets/`, `manifests/`, provenance, and quality handoff in
  one bounded package.
- Eval JSONL manifests belong under `corpus/manifests/eval/**`.

## Cleanup Status - 2026-05-15

- Empty directories: none found.
- Immediate physical delete: none.
- Physical rename: blocked until code references move through resolver aliases.
- Main cleanup gap: official data still lives under legacy `imported-gold/`
  names, while KMSC already shows the cleaner package shape.

## Operational Rule

- Import from `corpus/**` into PostgreSQL.
- Rebuild Qdrant from PostgreSQL/corpus chunks.
- Serve runtime answers from PostgreSQL/Qdrant/storage, not from this folder.
- v0.1.5에서 `embedding_text`와 payload schema가 바뀌면 Qdrant는 drop & rebuild 대상이다.
- If a folder is empty and not created by runtime code, remove it instead of
  keeping a placeholder.
