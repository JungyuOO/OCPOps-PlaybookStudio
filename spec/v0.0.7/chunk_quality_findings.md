# v0.0.7 Chunk Quality Findings

## Baseline

### Official corpus

- Source: `corpus/sources/official/imported-gold/gold_corpus_ko/chunks.jsonl`
- Report:
  - `spec/v0.0.7/evidence/v007_official_chunk_quality_baseline.json`
  - `spec/v0.0.7/evidence/v007_official_chunk_quality_baseline.md`
- Chunks: `27907`
- Token p50/p90/p95/max: `181 / 219 / 229 / 363`
- Char p50/p90/max: `436 / 659 / 1305`
- Command chunks: `15397` (`0.5517`)
- Major issues:
  - `raw_code_markup`: `14508`
  - `command_dense_chunk`: `7927`
  - `high_latin_ratio_ko_chunk`: `8406`
  - `code_plus_navigation`: `358`
  - `mixed_procedure_navigation`: `150`
  - `oversized_chunk`: `313`

판단:

- official corpus는 전체 크기 자체보다 내부 `[CODE]`, `[TABLE]` 태그가 retrieval/answer context에 남는 문제가 크다.
- command/procedure/troubleshooting chunk는 prefix와 본문을 합치면 설정값보다 커지는 케이스가 있다.
- 재청킹 시 section prefix token을 예산에서 제외하고, command/procedure/troubleshooting profile을 concept보다 작게 가져가야 한다.

### User/study course corpus

- Source: `corpus/sources/kmsc/parsed-preview/course_pbs/chunks.jsonl`
- Report:
  - `spec/v0.0.7/evidence/v007_user_study_chunk_quality_baseline.json`
  - `spec/v0.0.7/evidence/v007_user_study_chunk_quality_baseline.md`
- Chunks: `523`
- Token p50/p90/p95/max: `25 / 62 / 72 / 125`
- Char p50/p90/max: `171 / 423 / 623`
- Command chunks: `125` (`0.239`)
- Major issues:
  - `undersized_chunk`: `160`
  - `command_dense_chunk`: `13`

판단:

- 사용자/강의 corpus는 oversized보다 짧은 청크가 많다.
- 다만 course chunk schema는 `text`가 아니라 `index_texts.dense_text`, `search_text`, `body_md` 중심이므로 audit/retrieval 도구가 다양한 본문 필드를 읽어야 한다.
- 짧은 청크라도 `title`, `stage`, `dense_text`, `visual_text`, slide metadata가 결합되어 있으면 검색 단서가 유지된다.

## Applied Changes

- `chunk_quality_audit`가 `text` 외에 `embedding_text`, `search_text`, `body_md`, `markdown`, `index_texts.dense_text`를 읽도록 확장했다.
- official 재청킹 경로에서 내부 `[CODE]`, `[TABLE]` markup을 markdown 코드블록/표 텍스트로 렌더링하도록 했다.
- official import 경로에서도 기존 generated chunk를 DB에 넣을 때 내부 markup을 정규화하도록 했다.
- official chunk profile을 section role 기반으로 분리했다.
  - command/procedure/troubleshooting: smaller profile
  - concept/overview: context-preserving profile
  - reference-heavy: 기존 book slug 정책 유지
- `chunk_sections()`에서 section prefix token을 chunk budget에 반영해 prefix 때문에 최종 chunk가 커지는 문제를 줄였다.
- 사용자 문서 chunk embedding text에 section path를 항상 포함해 split 후에도 heading context가 유지되도록 했다.
- terminal local shell fallback을 제거했다.

## Remaining Work

- 실제 official corpus 파일 자체를 재생성할지 결정해야 한다.
- 큰 generated artifact를 커밋하기 전, 재생성 명령과 산출물 크기를 확인해야 한다.
- v0.0.6 command-learning smoke를 재실행해 short command query 개선 여부를 확인해야 한다.
- chunk 개선 후에도 command lookup이 흔들리면 intent classification agent를 retrieval policy 생성기로 추가한다.
