# v0.1.4 Term Bridge

Date: 2026-05-15

Purpose: S가 쓰던 metadata/corpus 용어와 J의 v0.1.4 schema 용어를 하나로 맞춘다.

이 문서는 새 schema를 추가로 제안하는 문서가 아니다. 기존 S 작업에서 쓰던 말이 v0.1.4의 어떤 테이블/컬럼/segment로 흡수되어야 하는지 정하는 브릿지다.

## Canonical Rule

v0.1.4 이후 협업 기준 용어는 J spec을 따른다.

- 원본 보존: `Parsing layer`
- 검색/답변 truth: `Corpus layer`
- 벡터 검색 projection: `Qdrant`
- 사람이 읽는 산출물: Reader/viewer artifact
- 폴더 안 JSON/JSONL: seed/import/evidence, runtime truth 아님

S가 기존에 쓰던 `Metadata Spine`은 독자 체계로 유지하지 않는다. 아래 v0.1.4 schema로 흡수한다.

## Layer Bridge

| 기존 표현 | v0.1.4 기준 | 비고 |
| --- | --- | --- |
| 원문 | `document_sources` + `document_versions` + storage | 원본 URI, 파일, sha256, 버전 |
| 파싱본 | `parsed_documents` | parser가 본 그대로. 검색/답변 금지 |
| 목차 | `parsed_documents.outline`, `document_blocks`, `corpus_chunks.navigation_only` | 본문 embedding 대상이 아니라 구조/길찾기 |
| 문단/코드/표/이미지 조각 | `document_blocks` | chunk 이전 원자 단위 |
| 이미지/도표/첨부 | `document_assets` | 이후 `image_ref` segment가 참조 |
| 청크 | `corpus_chunks` | 검색/인용 기본 단위 |
| 청크 본문 | `corpus_chunk_segments` | prose/command/output/table/image로 분리 |
| 명령어 | `corpus_chunk_commands` | env_scope, placeholders, privilege까지 구조화 |
| 다음 단계/관련 항목 | `corpus_chunk_refs` | `next_refs` jsonb 폐기 대상 |
| 추천질문/후속질문 | `corpus_question_candidates` | starter/followup/env_clarification |
| Qdrant payload | deterministic projection from `corpus_chunks` | 본문 segments는 payload에 넣지 않음 |

## Metadata Spine Field Bridge

| S 기존 필드 | v0.1.4 target | 판단 |
| --- | --- | --- |
| `source_scope` | `corpus_documents.corpus_scope`, `corpus_chunks.corpus_scope`, Qdrant payload `corpus_scope` | 공식/운영/업로드/course 검색 boundary |
| `document_source_id` | `corpus_documents.document_source_id` | source lineage |
| `parsed_document_id` | `corpus_documents.parsed_document_id`, `corpus_chunks.parsed_document_id` | parser lineage |
| `chunk_id` | `corpus_chunks.id` | Qdrant point id와 연결 |
| `topic` | `domain`, `task_intent`, `lifecycle_phase`, `facets` | `topic` 단일 필드 유지 금지 |
| `semantic_role` | `chunk_type`, `chunk_role`, `segment_type`, `segment_role` | 역할은 chunk/segment 양쪽으로 분해 |
| `k8s_objects` | `corpus_chunks.k8s_objects`, `resource_kinds`, `api_groups` | object 이름과 Kind/API group 분리 |
| `cli_commands` | `corpus_chunks.cli_command_names` + `corpus_chunk_commands` | 검색 신호와 답변 렌더링 원본 분리 |
| `error_strings` | `corpus_chunks.error_strings`, `symptom_terms` | 원문 에러와 정규화 증상 분리 |
| `verification_hints` | `corpus_chunks.verification_hints`, `verification` segment, `verify` ref | 문장/segment/ref로 나눠야 함 |
| `answerable_questions` | `corpus_question_candidates` | JSON array로 숨기지 않음 |
| `metadata_confidence` | `label_provenance`, `corpus_chunk_refs.confidence`, question `quality_status` | 전역 confidence 컬럼으로 두지 않음 |

## Topic To v0.1.4 Mapping

기존 `topic` 값은 다음처럼 분해한다.

| 기존 topic | `domain` | `task_intent` 후보 | `lifecycle_phase` 후보 | facets 후보 |
| --- | --- | --- | --- | --- |
| `install` | `install` | `install`, `configure`, `verify` | `plan`, `prepare`, `install`, `post_install` | `facets.install.*` |
| `networking` | `networking` | `configure`, `verify`, `troubleshoot`, `operate` | `operate`, `recover` | `facets.networking.*` |
| `security` | `security`, `authentication`, `authorization` | `configure`, `verify`, `troubleshoot` | `operate`, `recover` | `facets.security.*` |
| `storage` | `storage` | `configure`, `verify`, `troubleshoot`, `operate` | `operate`, `recover` | `facets.storage.*` |
| `monitoring` | `monitoring` | `verify`, `observe`, `troubleshoot`, `operate` | `operate`, `recover` | component/operator fields |
| `troubleshooting` | `troubleshooting` or source domain | `troubleshoot`, `verify` | `recover`, `operate` | `symptom_terms`, `error_strings` |
| `ops` | best matching domain | `operate`, `verify`, `troubleshoot` | `operate`, `recover` | KMSC/customer facets |

Rule: `domain`은 문서/청크가 속한 큰 영역이고, `task_intent`는 사용자가 뭘 하려는지다. 둘을 하나로 뭉치지 않는다.

## Semantic Role To Chunk/Segment Mapping

| 기존 `semantic_role` | `chunk_type` | `segment_type` | `segment_role` |
| --- | --- | --- | --- |
| `concept` | `concept` | `prose`, `image_ref` | `reference` 가능 |
| `procedure` | `procedure` | `prose`, `command`, `command_output`, `table` | `step`, `verification` |
| `command` | `command` | `command`, `command_output` | 없음 또는 `verification` |
| `config` | `procedure`, `reference` | `code`, `command`, `table` | `example`, `step` |
| `troubleshooting` | `troubleshooting` | `prose`, `command`, `command_output`, `warning` | `step`, `verification`, `caveat` |
| `reference` | `reference` | `prose`, `table`, `code`, `image_ref` | `reference` |
| `navigation` | `navigation` | 필요 시 생략 | `navigation_only=true` |

Rule: `semantic_role`은 그대로 저장하는 최종 필드가 아니다. chunk와 segment의 책임으로 쪼갠다.

## Text 4-Layer Bridge

| 기존 표현 | v0.1.4 target | 쓰임 |
| --- | --- | --- |
| `original_text` | `parsed_documents.raw_text` 또는 `document_blocks.text` | parser가 본 원문 보존 |
| `parsed markdown` | `document_blocks.markdown`, Reader 표시용 `markdown` | 사람이 읽는 표시 |
| `chunk_text` | segments에서 derived되는 `normalized_text` 또는 호환 view | BM25/정확검색 |
| `embedding_text` | `corpus_chunks.embedding_text` | vector embedding 입력 |
| `[CODE]...[/CODE]` 포함 text | `document_blocks` -> `corpus_chunk_segments` | legacy import 시 분해 |

Rules:

- `embedding_text`에는 code fence, `[CODE]`, `[TABLE]`, anchor URL, viewer path를 넣지 않는다.
- 명령어 자체는 embedding_text에 의미 신호로 들어갈 수 있지만, 답변 렌더링 원본은 `corpus_chunk_commands`다.
- 표시는 `markdown`, 검색은 `normalized_text`, 벡터는 `embedding_text`로 분리한다.

## Command / YAML / Code Bridge

| 원문 형태 | Parsing target | Corpus target | 비고 |
| --- | --- | --- | --- |
| `oc get pvc -n <namespace>` | `document_blocks.block_type=code`, `block_role=command` | `segment_type=command`, `corpus_chunk_commands` | command_template 보존 |
| 명령 출력 표 | `block_type=code_output`, `block_role=output` | `segment_type=command_output` | expected output 카드 |
| YAML manifest | `block_type=code`, `code_language=yaml` | `segment_type=code`, `language=yaml` | command로 오인 금지 |
| JSON snippet | `block_type=code`, `code_language=json` | `segment_type=code`, `language=json` | 구조 보존 |
| 일반 표 | `block_type=table`, `table_data` | `segment_type=table` | markdown table 렌더 가능 |
| 이미지 캡션/OCR | `document_assets`, `document_blocks.ocr_text` | `segment_type=image_ref`, `asset_id` | asset evidence 필수 |

Rule: 특수문자/공백을 일괄 제거하지 않는다. YAML indentation, quotes, CLI flags, paths, regex, URLs는 의미 데이터다.

## Question / Followup Bridge

| 기존 표현 | v0.1.4 target |
| --- | --- |
| `answerable_questions` | `corpus_question_candidates.question_type=starter/followup/command_lookup/troubleshooting` |
| `starter_question_candidates` jsonb | `corpus_question_candidates` |
| `followup_question_candidates` jsonb | `corpus_question_candidates` |
| `learning.next_refs` jsonb | `corpus_chunk_refs.ref_type=next` |
| topology next/related | `corpus_chunk_refs.ref_type=related/next/prerequisite/verify` |
| 환경 확인 질문 | `corpus_chunk_commands.requires_env_clarification` + `corpus_question_candidates.question_type=env_clarification` |

Rules:

- 질문 후보는 chunk metadata 안에 숨기지 않는다.
- `quality_status=rejected` 질문은 노출 금지.
- J가 답변 후속질문을 만들 때는 사용된 citations의 `corpus_question_candidates`와 `corpus_chunk_refs`를 본다.

## Qdrant Payload Bridge

Qdrant는 corpus의 deterministic projection이다.

Payload에 들어갈 것:

- `chunk_id`
- `corpus_document_id`
- `title`
- `section_path`
- `book_slug`
- `domain`
- `doc_type`
- `platform`
- `provider`
- `ocp_version`
- `locale`
- `task_intent`
- `lifecycle_phase`
- `audience_level`
- `privilege_scope`
- `chunk_type`
- `navigation_only`
- `cli_command_names`
- `k8s_objects`
- `operator_names`
- `error_strings`
- `visibility`
- `corpus_scope`
- `source_url`
- `viewer_artifact_path`

Payload에 넣지 않을 것:

- full segment body
- raw source text
- large markdown
- image binary
- arbitrary metadata blob
- internal `[CODE]` markup

Rule: payload schema가 바뀌면 `payload_version`을 올리고 재인덱싱해야 한다. v0.1.5에서는 새 `embedding_text` 기준으로 drop & rebuild가 전제다.

## Current DB Compatibility Bridge

현재 DB는 v0.1.4와 아직 다르다. dry-run에서는 아래처럼 본다.

| Current table/field | v0.1.4 target | Gap |
| --- | --- | --- |
| `document_sources.source_scope` | `source_collection`, `corpus_scope` | 이름과 역할 분리 필요 |
| `document_sources.metadata` | source-kind metadata | 검색/답변 필드는 넣지 말 것 |
| `parsed_documents.markdown` | `raw_text` + display `markdown` 분리 | 현재 parser output과 display text가 섞임 |
| `document_chunks.markdown` | `corpus_chunk_segments` | blob 분해 필요 |
| `document_chunks.embedding_text` | `corpus_chunks.embedding_text` | 내부 태그/URL 포함 여부 audit 필요 |
| `document_chunks.metadata` | typed columns + facets + limited metadata | 검색 필드는 column/related table로 승격 필요 |
| `document_chunks.starter_question_candidates` | `corpus_question_candidates` | jsonb 폐기 대상 |
| `document_chunks.followup_question_candidates` | `corpus_question_candidates` | jsonb 폐기 대상 |
| `document_chunks.asset_ids` | `document_assets` + `image_ref` segments | evidence join 명확화 필요 |
| `qdrant_index_entries.payload_hash` | `payload_hash` + `payload_version` | `payload_version` 누락 |

## Do Not Map This Way

아래 매핑은 금지한다.

- `topic`을 그대로 새 컬럼으로 추가
- `semantic_role`을 그대로 최종 schema에 유지
- `answerable_questions`를 `corpus_chunks.metadata` 안에 계속 저장
- `review_status`/`trust_score`를 지금부터 모든 chunk에 강제로 추가
- `document_chunks.markdown`을 계속 LLM prompt의 본문 truth로 사용
- Qdrant payload에 full text와 giant metadata를 다 넣기
- `Gold` 폴더명을 제품 Gold 상태로 해석
- 이미지를 PNG 파일 존재만으로 "챗봇 근거 연결 완료"라고 말하기

## S/J Handoff Vocabulary

S가 J에게 넘길 때 쓰는 말:

- `source inventory`: source/runtime/candidate/repair 숫자
- `parsing evidence`: source, version, parser, blocks, assets
- `corpus evidence`: chunks, segments, commands, refs, question candidates
- `projection evidence`: Qdrant payload version, index count, parity
- `quality blockers`: code loss, page stub, asset missing, topology missing, mojibake
- `golden questions`: expected chunk ids and citation requirements

J가 S에게 돌려줘야 하는 말:

- selected `chunk_id`
- selected `corpus_document_id`
- reranker result
- citations
- missing field or wrong payload reason
- failure class: `corpus_gap`, `retrieval_gap`, `answer_gap`, `citation_gap`

## Open Checks

- J planner references detailed `Text 4계층 계약`, `Encoding Contract`, `Reindex Plan`; current `db-corpus-schema.md` should get matching detailed sections or point to a separate doc.
- `study_docs` current DB scope should map to v0.1.4 `operations_docs` or `course_runtime` by package purpose.
- `user_upload` currently has `sources=10`, `parsed_docs=14`, `quality_snapshots=12`; dry-run must define current parsed/version selection.
