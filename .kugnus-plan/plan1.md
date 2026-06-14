# PBS 기능별 작업 계획

> 초기 참고안이다.
> 현재 실행 기준은 `pbs-enhancement-plan.md`, `pgvector-acceptance-check.md`, `rag-foundation/05-go-no-go.md`를 우선한다.

## 요약

우선순위는 파이프라인 점검이 1순위다.
업로드 문서가 원문 형태를 잃지 않고 파싱, 청킹, 색인, 검색, 답변, Viewer 표시까지 이어지는지 먼저 확인한다. 이후 Chat, Viewer, Wiki, Playbook, Book Factory, 작업 이력을 기능별로 고도화한다.

## Plan 1. 업로드 파이프라인 점검

| 항목 | 내용 |
|---|---|
| 현재 상태 | 업로드는 `received -> store -> parse -> chunk -> persist -> index -> scope -> ready` 순서로 처리된다. |
| 작업 | 샘플 문서 기준으로 원문, 파싱 결과, 청크, 저장 데이터, 색인 데이터, Viewer 표시 결과를 단계별로 대조한다. |
| 수정 대상 | `src/play_book_studio/http/upload_api.py`, `src/play_book_studio/ingestion/document_parsing.py`, 업로드 관련 테스트 |
| 완료 조건 | pass: 업로드 후 각 단계 산출물이 추적 가능하고 Viewer에서 원문 위치로 연결된다. fail: 특정 단계 결과가 누락되거나 원문 위치를 확인할 수 없다. |
| 검증 방법 | 업로드 API 테스트, 업로드 리포트 확인, Viewer 문서 조회, 저장된 청크의 `source_anchor`, `viewer_path`, `section_path` 확인 |

## Plan 2. 청킹 기준 정리

| 항목 | 내용 |
|---|---|
| 현재 상태 | 청킹은 제목, 글자 수, 블록 겹침, 표, 코드, 이미지 블록 기준을 함께 사용한다. |
| 작업 | 청크가 문맥을 잃지 않도록 제목, 섹션 경로, 표, 코드, 이미지 설명, 원문 위치가 유지되는지 기준을 고정한다. |
| 수정 대상 | `src/play_book_studio/ingestion/document_parsing.py`, 청킹 단위 테스트 |
| 완료 조건 | pass: 청크만 봐도 어느 문서의 어느 섹션인지 확인 가능하다. fail: 청크 내용이 잘렸거나 표/코드/이미지 설명이 분리되어 의미가 깨진다. |
| 검증 방법 | 제목 문서, 표 문서, 코드 문서, 이미지 포함 문서, 긴 문서 샘플로 청크 결과 비교 |

## Plan 3. 검색 범위 확인

| 항목 | 내용 |
|---|---|
| 현재 상태 | 검색은 공식 문서, 업로드 문서, 내부 문서 범위를 구분하는 구조가 있다. |
| 작업 | 사용자가 선택한 문서, 업로드 문서, 전체 문서 검색 범위가 의도대로 적용되는지 확인한다. |
| 수정 대상 | `src/play_book_studio/retrieval/access_scope.py`, `src/play_book_studio/retrieval/retriever_plan.py`, 검색 테스트 |
| 완료 조건 | pass: 선택한 문서 질문은 해당 문서 청크를 우선 사용한다. fail: 관련 없는 문서가 우선 검색되거나 선택 문서가 무시된다. |
| 검증 방법 | 같은 질문을 문서 선택 상태와 전체 검색 상태에서 실행해 참조문서 차이를 확인 |

## Plan 4. Chat-Viewer 연결

| 항목 | 내용 |
|---|---|
| 현재 상태 | Chat 답변에는 참조문서 링크와 Viewer 이동 정보가 포함될 수 있다. |
| 작업 | 답변의 참조문서를 클릭하면 Viewer가 해당 문서와 위치를 연다. OpenShift Lightspeed 답변 연동 시에도 같은 화면 흐름으로 표시한다. |
| 수정 대상 | `apps/web/src/pages/WorkspacePage.tsx`, `apps/web/src/pages/workspace/WorkspaceAnswer.tsx`, `apps/web/src/lib/runtimeApi.ts` |
| 완료 조건 | pass: 답변 참조문서 클릭 시 Viewer가 정확한 문서 위치를 연다. fail: Viewer가 열리지 않거나 다른 문서가 열린다. |
| 검증 방법 | Chat 질문, 참조문서 클릭, Viewer 경로와 표시 위치 확인 |

## Plan 5. Viewer 기록 저장

| 항목 | 내용 |
|---|---|
| 현재 상태 | Viewer에는 카드보기, 전체보기, 메모, 체크, 낙서 관련 기능이 존재한다. |
| 작업 | Viewer에서 남긴 메모, 체크, 낙서가 문서와 위치 기준으로 저장되고 다시 열었을 때 복원되게 한다. |
| 수정 대상 | `apps/web/src/pages/workspace/WorkspaceViewerPanel.tsx`, `apps/web/src/lib/runtimeApi.ts`, Viewer 저장 API |
| 완료 조건 | pass: 새로고침 후에도 같은 문서 위치에 기록이 남는다. fail: 기록이 사라지거나 다른 위치에 표시된다. |
| 검증 방법 | Viewer에서 기록 작성, 저장, 새로고침, 문서 재진입 후 복원 확인 |

## Plan 6. 답변 기록 정리

| 항목 | 내용 |
|---|---|
| 현재 상태 | Chat 답변과 히스토리 저장 구조가 있다. |
| 작업 | 질문, 답변, 참조문서, Viewer 이동 정보, 사용자 메모를 하나의 기록으로 조회할 수 있게 정리한다. |
| 수정 대상 | Chat 저장소, Chat API, Workspace 화면 |
| 완료 조건 | pass: 이전 답변을 열면 답변 내용, 참조문서, Viewer 연결이 함께 복원된다. fail: 답변만 남고 참조문서나 Viewer 연결이 사라진다. |
| 검증 방법 | Chat 질문 후 히스토리 재조회, 참조문서 클릭, Viewer 표시 확인 |

## Plan 7. Wiki 후보 정리

| 항목 | 내용 |
|---|---|
| 현재 상태 | Wiki와 Viewer 표시 구조가 존재한다. |
| 작업 | Chat 답변이나 문서 조각을 바로 Wiki로 확정하지 않고, 후보로 모아 관리자가 검토할 수 있게 한다. |
| 수정 대상 | Wiki 관련 저장소, Wiki API, Workspace 화면 |
| 완료 조건 | pass: 후보 상태와 확정 상태가 구분된다. fail: 검토 전 내용이 Wiki 문서처럼 표시된다. |
| 검증 방법 | 답변 저장, 후보 목록 확인, 확정 처리, Wiki Viewer 표시 확인 |

## Plan 8. Playbook 후보 정리

| 항목 | 내용 |
|---|---|
| 현재 상태 | Playbook 생성 흐름과 관련 저장 구조가 있다. |
| 작업 | 답변에서 절차, 명령어, 확인 항목을 분리해 Playbook 후보로 저장한다. |
| 수정 대상 | Playbook 생성 로직, 답변 처리 로직, Playbook 화면 |
| 완료 조건 | pass: 절차, 명령어, 확인 항목이 구분되어 저장된다. fail: 일반 답변 텍스트가 그대로 Playbook으로 저장된다. |
| 검증 방법 | 장애 대응 질문 실행, Playbook 후보 생성, 항목별 저장 데이터 확인 |

## Plan 9. Book Factory 정리

| 항목 | 내용 |
|---|---|
| 현재 상태 | 답변하지 못한 질문을 수집하려는 흐름이 있다. |
| 작업 | 답변 실패, 낮은 근거, 사용자 저장 요청을 기준으로 Book Factory에 후보를 남긴다. 자동 반영은 하지 않는다. |
| 수정 대상 | Book Factory 관련 API, Chat 답변 처리, 관리 화면 |
| 완료 조건 | pass: 질문, 실패 이유, 필요한 자료, 관련 문서가 후보로 저장된다. fail: 근거 없는 답변이 자동으로 문서화된다. |
| 검증 방법 | 답변 실패 케이스 실행, 후보 저장 여부, 관리 화면 조회 확인 |

## Plan 10. 작업 이력 연결

| 항목 | 내용 |
|---|---|
| 현재 상태 | 터미널 세션과 작업 이벤트 저장 테스트가 존재한다. |
| 작업 | 명령어, 로그, 적용 결과를 Chat 답변과 Viewer 문서 기록에 연결한다. |
| 수정 대상 | 터미널 세션 저장소, 작업 이력 API, Workspace 화면 |
| 완료 조건 | pass: 특정 답변에서 실제 실행 이력과 결과를 확인할 수 있다. fail: 답변과 실행 이력이 따로 조회된다. |
| 검증 방법 | 명령 실행, 결과 저장, Chat 기록에서 작업 이력 연결 확인 |

## 검증 순서

1. 업로드 파이프라인 테스트
2. 청킹 단위 테스트
3. 검색 범위 테스트
4. Chat 답변 참조문서 테스트
5. Viewer 기록 저장 테스트
6. Wiki 후보 저장 테스트
7. Playbook 후보 저장 테스트
8. Book Factory 후보 저장 테스트
9. 작업 이력 연결 테스트

## 기본 기준

- 먼저 파이프라인과 청킹 품질을 고정한다.
- 그 다음 화면 기능을 붙인다.
- 자동 문서화는 바로 적용하지 않는다.
- 사용자 기록은 삭제보다 후보 저장을 우선한다.
- OpenShift Lightspeed는 공식 답변 연동 대상으로만 다룬다.
