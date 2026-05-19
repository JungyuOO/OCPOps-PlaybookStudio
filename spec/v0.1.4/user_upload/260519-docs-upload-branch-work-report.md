# feat/docs_uploads_S_v1 브랜치 작업 보고서

작성일: 2026-05-19  
브랜치: `feat/docs_uploads_S_v1`  
비교 기준: `cfb7895..8c4d34d`  
현재 HEAD: `8c4d34d feat: finalize user upload document pipeline`

이 문서는 `feat/docs_uploads_S_v1` 브랜치에서 수행한 전체 작업을 다음 작업자가 빠르게 파악할 수 있도록 정리한 handoff 문서다. 전체 코드 diff를 그대로 복사하지 않고, 수정한 파일과 변경 의미, 제품 동작 변화, 검증 결과를 중심으로 기록한다.

## 브랜치 커밋 범위

| Commit | 제목 | 핵심 의미 |
| --- | --- | --- |
| `553493e` | `feat: harden user upload ingestion pipeline` | 유저 업로드 ingest, DB 저장, Qdrant 인덱싱, owner scope, stage event의 기반을 강화했다. |
| `bf290b7` | `feat: harden upload ingestion viewer pipeline` | 업로드 문서 viewer, asset materialization, OCR JSON 저장, debug artifact, progress UX를 강화했다. |
| `c061283` | `fix: improve upload PDF layout and stage completion` | PDF 이미지/코드 layout, 페이지 경계 병합, stage completion 상태를 개선했다. |
| `8c4d34d` | `feat: finalize user upload document pipeline` | visual code box 기반 parser, active upload RAG, 긴 코드 접기 UX, 완료 보고서를 정리했다. |

## 작업 규모

| 항목 | 값 |
| --- | --- |
| 변경 파일 수 | 61 files |
| 추가 라인 | 13,836 insertions |
| 삭제 라인 | 796 deletions |
| 주요 범위 | frontend, upload API, parser, viewer, DB repository, Qdrant indexing, retrieval scope, tests, spec docs |

## 제품 관점 요약

유저 업로드 기능은 사용자가 PDF, DOCX, PPTX, XLSX, MD, TXT, HTML, 이미지 자료를 올렸을 때 다음 경험을 제공하는 기능으로 정리되었다.

1. 업로드 과정이 8단계 진행 UI와 로그로 보인다.
2. 원본 파일이 `storage/uploads/sources`에 저장된다.
3. PDF는 텍스트, 표, 이미지, 코드박스 레이아웃을 최대한 보존해 파싱된다.
4. 이미지 에셋과 OCR JSON은 `storage/uploads/assets/<document_source_id>` 아래에 저장된다.
5. 파싱 결과와 청크 진단은 `storage/uploads/reports/<document_source_id>` 아래에 저장된다.
6. PostgreSQL에는 source, version, parse job, parsed document, block, asset, chunk가 저장된다.
7. Qdrant에는 chunk embedding과 payload가 올라가고 `qdrant_index_entries`로 mapping된다.
8. 업로드 문서 viewer에서 본문, 이미지, 코드블록, 표를 확인할 수 있다.
9. active document 질문은 업로드 문서를 citation으로 잡고 답변한다.

## 이번 브랜치에서 닫은 주요 문제

| 문제 | 해결 |
| --- | --- |
| 업로드가 너무 빠르게 성공으로 보이고 실제 내용이 빈약했던 문제 | stage event와 fail-loud 성격의 상태 판정을 강화하고, parse/chunk/index 결과를 report로 남겼다. |
| PDF 제목만 보이거나 한글 본문/코드블록 구조가 무너지는 문제 | PyMuPDF layout block, table detector, image bbox, visual code region 기반 parser를 도입했다. |
| PDF 내부 이미지가 원본 문서와 분리되지 않고 확인이 어려운 문제 | image asset materialization과 OCR JSON 저장 경로를 정규화했다. |
| OCR 결과가 사람용 뷰어 본문에 그대로 노출되는 문제 | OCR은 검색 보조 metadata로 저장하고 viewer 본문에는 원문 구조와 이미지 중심으로 표시한다. |
| 코드블록 안의 `##` 주석이 heading처럼 표시되는 문제 | layout 기반 code block을 우선시해 literal hash line이 heading으로 승격되지 않게 했다. |
| `Project Name:`, `INCLUDE / EXCLUDE:` 같은 설명문이 코드블록으로 오분류되는 문제 | 한글 서술형 label line을 prose로 판별하는 guard를 추가했다. |
| 페이지가 나뉜 회색 코드박스가 여러 코드블록으로 찢어지는 문제 | PyMuPDF drawing rect에서 회색 코드 박스를 감지해 `visual_group`으로 병합했다. |
| directory tree가 YAML처럼 렌더링되는 문제 | `├`, `└`, `│` 문자가 있는 block은 `text` 코드블록으로 표시한다. |
| 업로드 문서 질문에 `ArgoCD`가 있으면 외부 제품으로 오판해 검색 전 차단되는 문제 | active document/repository scope가 있으면 unsupported product gate를 우회한다. |
| 코드블록 `Show more / Show less`가 기준 없이 붙어 보이는 문제 | 20줄 이상 코드만 기본 접힘 처리하고 `전체 보기 (N줄)` / `접기 (N줄)`로 표시한다. |

## 실제 검증 증거

### 대표 업로드 문서

파일: `12. CD(ArgoCD)(03.25).pdf`

| 항목 | 값 |
| --- | --- |
| document_source_id | `3ce81bf3-6261-4788-a3b6-bfc21ef24b14` |
| blocks | `93` |
| chunks | `26` |
| assets | `4` |
| Qdrant index | `26/26 indexed` |
| viewer route | `/uploads/documents/3ce81bf3-6261-4788-a3b6-bfc21ef24b14/index.html` |

확인한 내용:

- `overlays/dev/kustomization.yaml`이 하나의 YAML 코드블록으로 유지됨
- `namePrefix: dev-`, `# 개발 환경용 이미지 태그 고정`, `images`, `newTag`가 한 코드블록 안에 유지됨
- `Project Name`, `INCLUDE / EXCLUDE`, `path` 설명문은 코드가 아니라 문단으로 표시됨
- 긴 코드블록은 `전체 보기 (N줄)`로 접힘 표시됨
- 챗봇 질문 “개발 서버 배포 시 path 값은?”에 `path: 'overlays/dev'`로 답변하고 `ArgoCD에서 연결하는 방법` chunk를 citation으로 사용함

### 테스트와 빌드

```powershell
uv run pytest tests/test_retriever_plan.py tests/test_answer_router.py tests/test_document_parsing.py tests/test_viewer_code_blocks.py tests/test_upload_api.py tests/test_document_repository.py tests/test_company_llm_vision.py tests/test_session_owner_scoping.py -q
# 77 passed

npm --prefix apps/web run build
# passed

git diff --check
# passed
```

## 파일별 변경 내용

### Frontend shell / theme / workspace

| 파일 | 상태 | 변경 내용 |
| --- | --- | --- |
| `apps/web/src/components/AppHeader.css` | Added | 앱 공통 헤더 스타일을 추가했다. 테마와 workspace UI 정돈의 기반이다. |
| `apps/web/src/components/AppHeader.tsx` | Added | 공통 AppHeader 컴포넌트를 추가했다. |
| `apps/web/src/components/ThemeToggleButton.tsx` | Added | light/dark theme toggle 버튼을 추가했다. |
| `apps/web/src/lib/globalTheme.ts` | Added | 전역 테마 상태와 DOM 반영 로직을 추가했다. |
| `apps/web/src/lib/clusterProfile.ts` | Added | runtime/cluster profile 표시용 helper를 추가했다. |
| `apps/web/src/pages/WorkspacePage.tsx` | Modified | workspace 화면에서 새 header/theme 구조를 반영했다. |
| `apps/web/src/pages/workspace/WorkspaceHeader.tsx` | Modified | workspace header 표시와 runtime profile 연동을 조정했다. |
| `apps/web/src/lib/courseApi.ts` | Modified | runtime API 계약 변화에 맞춰 일부 타입/요청 처리를 정리했다. |
| `apps/web/src/lib/opsConsoleApi.ts` | Modified | runtime metadata와 owner/session 관련 payload 처리를 보강했다. |
| `apps/web/src/lib/runtimeApi.ts` | Modified | health/runtime payload에서 user upload, DB corpus, reranker, theme/profile 정보를 더 안정적으로 읽도록 확장했다. |

### Repository page / upload UX

| 파일 | 상태 | 변경 내용 |
| --- | --- | --- |
| `apps/web/src/pages/PlaybookLibraryPage.tsx` | Modified | 유저 업로드 8단계 UI, progress log, stage card, asset/OCR progress, viewer/report 연결, success/warn/error 판정을 확장했다. |
| `apps/web/src/pages/PlaybookLibraryPage.css` | Modified | 업로드 stage card, progress panel, dark/light theme, logs, supported inputs, upload viewer entry UI를 정리했다. |
| `apps/web/src/components/ViewerDocumentStage.tsx` | Modified | viewer 내부 copy/wrap/collapse button 동작 fallback을 업데이트했다. `Show more/less` 대신 한국어 label fallback을 사용한다. |

### Runtime / infra

| 파일 | 상태 | 변경 내용 |
| --- | --- | --- |
| `docker-compose.yml` | Modified | app runtime에서 필요한 path/env 반영을 보강했다. |
| `src/play_book_studio/runtime_catalog_registry.py` | Modified | runtime catalog registry의 writable path/seed input 판단을 보강했다. |
| `src/play_book_studio/cli.py` | Modified | runtime maintenance 또는 seed path 관련 CLI 처리를 보강했다. |
| `src/play_book_studio/ingestion/corpus_import.py` | Modified | runtime path와 corpus import 계약 변화에 맞춘 보정이 들어갔다. |

### Upload API / storage / DB

| 파일 | 상태 | 변경 내용 |
| --- | --- | --- |
| `src/play_book_studio/http/upload_api.py` | Modified | 업로드 ingest 핵심. 파일 저장, parse progress, chunk 생성, DB 저장, asset materialization, Qdrant indexing, report 생성, delete cleanup, stream event를 대폭 강화했다. |
| `src/play_book_studio/db/document_repository.py` | Modified | document source/repository/owner/visibility/source_scope 저장, duplicate handling, asset/chunk persistence, delete cascade 조회를 보강했다. |
| `src/play_book_studio/db/qdrant_indexer.py` | Modified | Qdrant payload에 owner, repository, document source, source scope를 포함하고 index entry mapping을 강화했다. |
| `src/play_book_studio/http/document_status_api.py` | Modified | owner visibility 기준의 document status 조회를 보강했다. |
| `src/play_book_studio/http/session_owner.py` | Modified | single-user owner, cookie/header owner 해시 처리와 session scope 일관성을 개선했다. |
| `src/play_book_studio/http/server_handler_factory.py` | Modified | upload ingest/delete/report, viewer, chat handler에 session owner를 주입하고 route 연결을 강화했다. |
| `src/play_book_studio/http/data_control_room_buckets.py` | Modified | data control room에서 user upload/runtime bucket 표시가 맞도록 조정했다. |

### Parser / OCR / viewer

| 파일 | 상태 | 변경 내용 |
| --- | --- | --- |
| `src/play_book_studio/ingestion/document_parsing.py` | Modified | PDF parser 핵심. PyMuPDF layout block, table extraction, image bbox, wrapped line repair, visual code region, prose guard, directory tree language, page-cross code fence merge를 추가했다. |
| `src/play_book_studio/ingestion/vision.py` | Modified | Company LLM endpoint 기반 image describer/OCR 경로를 정리하고 Qwen 명칭 의존을 제거했다. |
| `src/play_book_studio/http/server_routes_viewer.py` | Modified | upload document viewer HTML을 추가/확장했다. parsed markdown, asset source, chunk diagnostic, copy/wrap/collapse controls, dark reader CSS를 제공한다. |
| `src/play_book_studio/http/viewer_blocks_rich.py` | Modified | code block rendering에 copy/wrap/collapse control, YAML highlighting, 20줄 이상 collapse 기준을 적용했다. |
| `src/play_book_studio/http/viewer_page.js` | Modified | viewer code block copy/wrap/collapse 동작 label을 정리했다. |

### Retrieval / answering

| 파일 | 상태 | 변경 내용 |
| --- | --- | --- |
| `src/play_book_studio/retrieval/access_scope.py` | Modified | active document/repository와 owner scope filtering을 정리했다. |
| `src/play_book_studio/retrieval/retriever_plan.py` | Modified | active document/repository 질문에서는 unsupported external product gate를 우회하도록 했다. |
| `src/play_book_studio/answering/answerer.py` | Modified | active document/repository context가 있으면 router의 unsupported product 차단을 우회하도록 넘긴다. |
| `src/play_book_studio/answering/router.py` | Modified | `allow_unsupported_product` 옵션을 추가했다. |
| `src/play_book_studio/answering/context.py` | Modified | uploaded source와 owner/document context가 retrieval context에 반영되도록 보강했다. |

### Tests

| 파일 | 상태 | 변경 내용 |
| --- | --- | --- |
| `tests/test_upload_api.py` | Modified | upload ingest, duplicate, report, asset materialization, indexing failure, delete/report 동작 테스트를 보강했다. |
| `tests/test_document_parsing.py` | Modified | PDF title, wrapped Korean line, code block, image bbox, visual code region, prose guard, directory tree language 테스트를 추가했다. |
| `tests/test_document_repository.py` | Modified | repository/document owner, visibility, source_scope, chunk/asset 저장 테스트를 보강했다. |
| `tests/test_qdrant_indexer.py` | Modified | Qdrant payload와 index entry 계약을 보강했다. |
| `tests/test_retrieval_access_scope.py` | Modified | owner/private upload access scope 테스트를 보강했다. |
| `tests/test_session_owner_scoping.py` | Modified | session owner 기반 private document scoping 테스트를 추가/보강했다. |
| `tests/test_answer_context_metadata.py` | Modified | answer context metadata에 upload scope가 포함되는지 테스트를 보강했다. |
| `tests/test_answer_router.py` | Modified | active upload 질문의 external product bypass 테스트를 추가했다. |
| `tests/test_retriever_plan.py` | Added | active document scope가 unsupported product gate를 우회하는지 테스트한다. |
| `tests/test_viewer_code_blocks.py` | Modified | copy payload, YAML highlighting, 20줄 이상 collapse 기준 테스트를 추가했다. |
| `tests/test_company_llm_vision.py` | Renamed/Modified | 기존 Qwen vision 테스트를 Company LLM/Gemma4 endpoint 개념에 맞게 리네이밍하고 갱신했다. |
| `tests/_support_app_viewers.py` | Modified | viewer HTML code block collapse/copy/wrap expectation을 갱신했다. |
| `tests/test_runtime_catalog_registry.py` | Added | runtime catalog registry path/seed input 판단 테스트를 추가했다. |
| `tests/test_runtime_seed_inputs.py` | Modified | runtime seed input 계약 변화에 맞게 테스트를 조정했다. |

### Spec / handoff docs

| 파일 | 상태 | 목적 |
| --- | --- | --- |
| `spec/v0.1.4/260517-embedding-cleanup-timeline.html` | Added | embedding cleanup 작업 타임라인 기록 |
| `spec/v0.1.4/260517-official-data-validation.html` | Added | official data validation 기록 |
| `spec/v0.1.4/260518-branch-work-report.html` | Added | v0.1.4 branch work 중간 보고 |
| `spec/v0.1.4/260518-eval-set-contract-audit.html` | Added | eval set contract 감사 기록 |
| `spec/v0.1.4/260518-official-corpus-rebuild-decision.html` | Added | official corpus rebuild 판단 기록 |
| `spec/v0.1.4/260518-official-data-validation-question-set.html` | Added | official data 검증 질문지 |
| `spec/v0.1.4/260518-retrieval-auto-audit.html` | Added | retrieval auto audit 기록 |
| `spec/v0.1.4/user_upload/260519-user-upload-8-stage-runtime-map.html` | Added | 유저 업로드 8단계 런타임 안내도 |
| `spec/v0.1.4/user_upload/260519-user-upload-pipeline-explained.md` | Added | 유저 업로드 파이프라인 설명 |
| `spec/v0.1.4/user_upload/260519-user-upload-ingestion-report-plan.html` | Added | ingestion report 설계와 저장 경로 계획 |
| `spec/v0.1.4/user_upload/260519-codex-user-upload-change-handoff.html` | Added | Codex 작업 handoff |
| `spec/v0.1.4/user_upload/트러블/260519-layout-classifier-trouble-report.html` | Added/Modified | layout classifier 문제와 해결 기록 |
| `spec/v0.1.4/user_upload/260519-user-upload-v014-completion-report.html` | Added | 유저 업로드 v0.1.4 완료 보고서 |
| `spec/v0.1.4/user_upload/260519-docs-upload-branch-work-report.md` | Added | 이 브랜치 전체 작업 Markdown 보고서 |
| `spec/v0.1.4/user_upload/260519-docs-upload-branch-work-report.html` | Added | 이 브랜치 전체 작업 HTML 보고서 |

## 저장 구조 요약

| 산출물 | 경로 |
| --- | --- |
| 원본 파일 | `storage/uploads/sources/<sha>/<filename>` |
| 파싱 결과 | `storage/uploads/reports/<document_source_id>/parsed.md` |
| 검색 청크 | `storage/uploads/reports/<document_source_id>/chunks.json` |
| 에셋 manifest | `storage/uploads/reports/<document_source_id>/assets-manifest.json` |
| ingestion report | `storage/uploads/reports/<document_source_id>/ingestion-report.json` |
| 이미지 에셋 | `storage/uploads/assets/<document_source_id>/images` |
| OCR JSON | `storage/uploads/assets/<document_source_id>/ocr` |
| HTML viewer | `/uploads/documents/<document_source_id>/index.html` |

## 남은 고도화 후보

| 우선순위 | 작업 |
| --- | --- |
| P1 | ambiguous block을 Gemma4 judge로 넘기는 layout classifier 고도화 |
| P1 | active document 질문에서 document-local retry와 citation coverage check 강화 |
| P1 | PDF 시각 구조가 없는 문서의 code/prose/table 분류 정확도 개선 |
| P2 | stale upload source/report/assets cleanup maintenance task |
| P2 | 업로드 UI에서 OCR/image progress를 더 세분화하고 병목 원인을 표시 |
| P2 | 대표 PDF regression corpus와 업로드 후 자동 질문지 생성 |
| P3 | private upload를 위키문서화하는 manifest/relation index 생성 |
| P3 | 공식 corpus 승격 후보 flow와 승인 UI 설계 |

## 다음 작업자가 확인할 것

1. `git diff cfb7895..8c4d34d -- <file>`로 파일별 실제 diff를 확인한다.
2. `storage/uploads/reports/<document_source_id>/parsed.md`와 viewer HTML이 같은 문서 구조를 보여주는지 확인한다.
3. active document 질문이 업로드 문서를 citation으로 잡는지 확인한다.
4. 삭제 API가 DB, Qdrant, source, report, asset directory를 모두 정리하는지 확인한다.
5. v0.1.5 작업에서는 이 private upload 구조를 공식 corpus 구조와 섞지 않고, manifest/relation/viewer 형태만 빌려 확장한다.
