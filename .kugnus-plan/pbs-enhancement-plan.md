# PBS 고도화 실행 계획

> 이 문서는 PBS 기능 고도화 참고 계획이다.
> 현재 수용 기준과 검증 결과는 `pgvector-acceptance-check.md`, `rag-foundation/05-go-no-go.md`를 우선한다.
> 회사 OpenShift Lightspeed 연동은 `company-openshift-lightspeed-next.md` 기준으로 별도 단계에서 확인한다.

## 기준 상태

| 항목 | 값 |
|---|---|
| branch | `dev` |
| head | `f2fb312` |
| 기준 검증 | `.kugnus-plan/rag-foundation/05-go-no-go.md` |
| RAG 판정 | `go`, `13/13 pass` |
| 실행 확인 | app `8765`, web `8080`, PostgreSQL + pgvector 실행 |
| CRC 확인 | 이전 로컬 조회 기록이며 현재 RAG 수용 기준에는 포함하지 않음 |

## 최종 목표

PBS 안에서 고객이 질문하고, 근거 문서를 열고, 확인 내용을 남기고, 이후 같은 문제를 다시 활용할 수 있는 운영 흐름을 완성한다.

최종 화면 흐름:

1. 고객이 PBS Workspace에서 질문한다.
2. PBS가 공식 문서, 고객 업로드 문서, 사내 학습 문서, 작업 이력 중 필요한 근거를 찾는다.
3. 답변에는 참조문서와 Viewer 이동 정보가 붙는다.
4. 고객은 Viewer에서 문서, 표, 코드, 이미지, 메모, 체크, 낙서를 한 화면에서 확인한다.
5. 답변과 사용자 기록은 히스토리에 남는다.
6. 반복 질문, 근거 부족 질문, 절차성 답변은 Wiki 후보 또는 Playbook 후보로 분리된다.
7. 관리자가 후보를 검토한 뒤 정식 문서로 반영한다.
8. OpenShift Lightspeed는 공식 운영 답변 연동 대상으로만 붙이고, PBS 화면 표시 규칙을 따른다.

## 판단 기준

| 기준 | 내용 |
|---|---|
| 우선순위 | RAG 품질, 근거 표시, Viewer 기록, 히스토리 복원, 재사용 후보 순서 |
| 사용자 기준 | 고객은 내부 파이프라인을 몰라도 질문, 근거, 기록, 재사용 흐름을 이해해야 한다 |
| 데이터 기준 | 답변, citation, Viewer path, 사용자 기록, 작업 이력이 같은 세션에서 추적되어야 한다 |
| 제외 | 자동 Wiki 확정, 근거 없는 Playbook 생성, OpenShift Lightspeed 자체 지식 재구축 |

## Plan 0. RAG 기초 고정

| 항목 | 내용 |
|---|---|
| 현재 상태 | 완료 |
| 작업 | 문서 수량, chunk 품질, embedding, pgvector 색인, 검색, 답변 근거, Viewer 연결 검증 |
| 수정 대상 | `kmsc_course_import.py`, `embedding_indexer.py`, `corpus_status.py`, audit 도구, 검색 신호 |
| 완료 조건 | pass: RAG audit `13/13 pass`. fail: pgvector 색인 누락, stale embedding 존재, Viewer 미연결 |
| 검증 방법 | `python -m play_book_studio.evals.rag_foundation_audit ...` |
| 현재 gap | 공식 문서 빈 embedding `89건`은 non-indexable 처리됨. row 단위 제외 사유 컬럼은 추가 필요 |

## Plan 1. 업로드 예외 처리

| 항목 | 내용 |
|---|---|
| 현재 상태 | 기본 구현 완료. 저장/파싱/청킹/DB 설정 단계 실패 시 `uploads/exceptions/<failure_id>/`에 failure report를 남김 |
| 작업 | 실패 파일을 예외 폴더로 분리하고 실패 단계, 원인, 원본 파일명, owner, report 경로를 남긴다 |
| 수정 대상 | `src/play_book_studio/http/upload_api.py`, `tests/test_upload_api.py` |
| 완료 조건 | pass: 실패 업로드가 예외 폴더와 report에 남고 정상 업로드는 기존 흐름 유지. fail: 실패 원인이 사라지거나 정상 업로드가 막힘 |
| 검증 결과 | pass: 잘못된 base64 failure report 생성, 빈 parse 결과 source 예외 폴더 이동, 업로드 관련 테스트 통과 |
| 남은 확인 | 실제 깨진 PDF, 지원하지 않는 확장자, 정상 PDF/PPTX 샘플 업로드 수동 확인 |
| 검증 방법 | 깨진 PDF, 빈 파일, 지원하지 않는 확장자, 정상 PDF/PPTX 샘플 업로드 테스트 |

## Plan 2. 업로드 chunk 품질

| 항목 | 내용 |
|---|---|
| 현재 상태 | 공식/KMSC RAG는 통과. 업로드 샘플별 품질 게이트는 더 촘촘해야 함 |
| 작업 | PDF, PPTX, 표, 이미지, 코드블록 샘플별 chunk audit을 만든다. title, section, page, asset, source_anchor 보존 여부를 숫자로 기록한다 |
| 수정 대상 | `src/play_book_studio/ingestion/document_parsing.py`, `src/play_book_studio/evals/chunk_quality_audit.py`, 업로드 샘플 fixture |
| 완료 조건 | pass: 업로드 chunk의 빈 embedding 대상 `0건`, viewer_path 누락 `0건`, source_anchor 누락 `0건`. fail: 원문 위치를 찾을 수 없는 chunk 존재 |
| 검증 방법 | 업로드 후 DB `document_chunks`, `chunk_embeddings`, report, Viewer 문서 대조 |

## Plan 3. 검색 범위 고정

| 항목 | 내용 |
|---|---|
| 현재 상태 | 공식 문서, 고객 문서, 사용자 업로드 범위를 구분하는 구조가 있음 |
| 작업 | 같은 질문을 전체 검색, 공식 문서만, 업로드 문서만, 선택 문서 기준으로 실행해 top-k 결과를 분리 기록한다 |
| 수정 대상 | `src/play_book_studio/retrieval/access_scope.py`, `src/play_book_studio/retrieval/retriever_plan.py`, `tests/test_retrieval_access_scope.py` |
| 완료 조건 | pass: 선택한 범위 밖 chunk가 top5에 들어오지 않음. fail: 사용자 업로드 질문에서 공식 문서가 우선됨 |
| 검증 방법 | 공식 질문 20개, KMSC 질문 10개, 업로드 질문 10개, 범위 밖 질문 5개 평가 |

## Plan 4. 답변과 Viewer 연결

| 항목 | 내용 |
|---|---|
| 현재 상태 | `/api/chat`, `/api/source-meta`, `/api/viewer-document` 연결 검증은 통과 |
| 작업 | 답변 citation 클릭 시 Viewer가 문서와 section 위치를 안정적으로 연다. 공식 문서, KMSC, 업로드 문서 모두 같은 동작으로 맞춘다 |
| 수정 대상 | `apps/web/src/pages/workspace/WorkspaceAnswer.tsx`, `apps/web/src/pages/workspace/WorkspaceViewerPanel.tsx`, `src/play_book_studio/http/server_routes_viewer.py` |
| 완료 조건 | pass: citation 클릭 200, 문서 title 일치, section 일치. fail: 답변은 맞지만 Viewer가 다른 위치를 엶 |
| 검증 방법 | 실제 `/api/chat` 응답 citation으로 source-meta와 viewer-document 재조회 |

## Plan 5. Viewer 기록 저장

| 항목 | 내용 |
|---|---|
| 현재 상태 | `favorite`, `check`, `note`, `ink`, `edited_card`, `recent_position` 저장 로직이 있음 |
| 작업 | 카드보기, 전체보기, 메모, 체크, 낙서가 같은 target_ref 기준으로 저장되고 다시 열 때 복원되게 화면과 API를 맞춘다 |
| 수정 대상 | `src/play_book_studio/http/wiki_user_overlay.py`, `apps/web/src/pages/llmwikibook/*`, `apps/web/src/pages/workspace/WorkspaceViewerPanel.tsx` |
| 완료 조건 | pass: 새로고침 후 같은 문서 위치에 메모, 체크, 낙서 복원. fail: 기록이 사라지거나 다른 문서에 표시됨 |
| 검증 방법 | Viewer에서 기록 작성, 저장 API 확인, 새로고침, 동일 문서 재진입 |

## Plan 6. 히스토리 복원

| 항목 | 내용 |
|---|---|
| 현재 상태 | `chat_sessions`, `chat_messages`에 질문, 답변, citation 저장 구조가 있음 |
| 작업 | 이전 답변을 열면 답변 본문, citation, Viewer 위치, 사용자 기록 연결이 함께 복원되게 한다 |
| 수정 대상 | `src/play_book_studio/db/chat_repository.py`, `src/play_book_studio/http/chat_history_api.py`, `apps/web/src/pages/WorkspacePage.tsx` |
| 완료 조건 | pass: 히스토리에서 이전 답변을 열고 citation 클릭 시 Viewer와 사용자 기록이 복원됨. fail: 답변 텍스트만 복원됨 |
| 검증 방법 | 질문 실행, 히스토리 조회, 메시지 재진입, Viewer 기록 재조회 |

## Plan 7. Wiki 후보와 Playbook 후보

| 항목 | 내용 |
|---|---|
| 현재 상태 | Wiki 화면, Playbook Library, 답변 품질 후보 조회 구조가 있음 |
| 작업 | 답변을 바로 문서화하지 않는다. 반복 질문, no_answer, clarification, 절차성 답변을 후보 상태로 저장하고 관리자 검토 뒤 확정한다 |
| 수정 대상 | `src/play_book_studio/http/chat_quality_api.py`, `src/play_book_studio/http/data_control_room.py`, `apps/web/src/pages/PlaybookLibraryPage.tsx`, Wiki 관련 화면 |
| 완료 조건 | pass: 후보, 검토중, 확정, 제외 상태가 구분됨. fail: 검토 전 답변이 정식 Wiki 또는 Playbook으로 표시됨 |
| 검증 방법 | 답변 실패 케이스, 반복 질문 케이스, 절차성 답변 케이스를 실행하고 후보 목록 확인 |

## Plan 8. 작업 이력 연결

| 항목 | 내용 |
|---|---|
| 현재 상태 | 터미널 세션, 명령 이벤트, OpenShift 리소스 조회 구조가 있음 |
| 작업 | 명령어, YAML, 이벤트, 로그, 적용 결과를 질문/답변/Viewer 기록과 연결한다 |
| 수정 대상 | `src/play_book_studio/http/terminal_ws.py`, `src/play_book_studio/db/terminal_learning_repository.py`, `src/play_book_studio/http/ops_console_api.py`, Workspace 화면 |
| 완료 조건 | pass: 답변 기록에서 실행 명령, 결과, 관련 리소스, 관련 문서를 함께 확인. fail: 작업 이력과 답변 기록이 따로 남음 |
| 검증 방법 | CRC에서 리소스 조회, 명령 실행, 결과 저장, 답변 히스토리에서 연결 확인 |

## Plan 9. OpenShift Lightspeed 답변 연동

| 항목 | 내용 |
|---|---|
| 현재 상태 | 현재 repo 기준 실제 연동 구현은 없음 |
| 작업 | OpenShift Lightspeed 답변을 PBS 답변 표시 규칙에 맞게 변환한다. PBS는 답변 본문, 근거, Viewer 표시, 히스토리 저장 형식을 유지한다 |
| 수정 대상 | 연동 API 모듈 신규 작성, `server_chat.py`, Workspace 답변 표시 |
| 완료 조건 | pass: OpenShift Lightspeed 답변도 PBS 답변처럼 citation, Viewer, 히스토리에 남음. fail: 별도 화면처럼 보이거나 근거 표시 규칙이 깨짐 |
| 검증 방법 | 공식 운영 질문 10개로 PBS 직접 답변과 OpenShift Lightspeed 연동 답변의 표시 형식 비교 |

## Plan 10. 화면 흐름 정리

| 항목 | 내용 |
|---|---|
| 현재 상태 | `/studio`, `/llmwikibook`, `/playbook-library`, `/course` 화면이 분리되어 있음 |
| 작업 | 고객 기준 기본 진입은 Workspace로 두고, Wiki와 Playbook은 기록을 재사용하는 화면으로 정리한다 |
| 수정 대상 | `apps/web/src/pages/WorkspacePage.tsx`, `apps/web/src/pages/LlmWikiBookPage.tsx`, `apps/web/src/pages/PlaybookLibraryPage.tsx`, route handoff |
| 완료 조건 | pass: 질문, Viewer, 기록, Wiki 후보, Playbook 후보 이동이 3클릭 안에 가능. fail: 사용자가 어느 화면에서 무엇을 해야 하는지 흐름이 끊김 |
| 검증 방법 | 사용자 흐름 5개를 정해 Playwright 또는 수동 화면 캡처로 확인 |

## 실행 순서

| 순서 | 작업 | 기준 |
|---|---|---|
| 1 | Plan 1 | 실패 업로드를 추적 가능하게 만든다 |
| 2 | Plan 2 | 업로드 chunk 품질을 숫자로 고정한다 |
| 3 | Plan 3 | 검색 범위 오염을 막는다 |
| 4 | Plan 4 | 모든 답변 근거를 Viewer로 연다 |
| 5 | Plan 5 | Viewer 기록을 저장/복원한다 |
| 6 | Plan 6 | 히스토리에서 답변과 근거를 복원한다 |
| 7 | Plan 7 | Wiki/Playbook 후보를 검토 상태로 관리한다 |
| 8 | Plan 8 | 작업 이력을 답변 기록에 연결한다 |
| 9 | Plan 9 | OpenShift Lightspeed 답변을 같은 표시 규칙에 맞춘다 |
| 10 | Plan 10 | 화면 이동을 고객 흐름 기준으로 정리한다 |

## 다음 작업 기준

다음 구현은 Plan 1부터 시작한다.

시작 전 확인:

- RAG audit `go` 유지
- 기존 서버 연결값 삭제 금지
- 기존 Docker 볼륨 삭제 금지
- 실패 파일은 숨기지 않고 예외 폴더와 report에 남김

Plan 1 완료 후 바로 Plan 2로 넘어가지 않는다. 업로드 실패/성공 샘플 결과를 보고 Plan 2 기준을 조정한다.
