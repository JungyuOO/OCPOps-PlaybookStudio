# OpenShift Lightspeed 호출 증명 보고

## 현재 확인

PBS 챗봇은 OpenShift 운영 질문을 받으면 OpenShift Lightspeed API를 우선 호출한다.

호출이 성공하면 OpenShift Lightspeed 답변을 공식 기준 답변으로 사용하고, PBS RAG 검색 결과를 함께 반영해 최종 답변을 만든다. 이때 `Lightspeed` 배지는 호출 성공 증거가 남은 경우에만 표시된다.

## 최근 실행 증거

실행 질문:

```text
Pod Pending 상태면 무엇을 먼저 확인해야 해?
```

확인 결과:

| 항목 | 값 |
|---|---|
| session_id | `report-proof-lightspeed-latest` |
| answer_source | `lightspeed_with_pbs_rag` |
| OpenShift Lightspeed status | `used` |
| primary badge | `Lightspeed` |
| related link badge | `Lightspeed` |
| Viewer path | `/external/lightspeed/0e7ac188f8aaa4499c8b` |
| artifact_id | `0e7ac188f8aaa4499c8b` |
| conversation_id | `a7803818-bda7-4d5f-a508-4a7d1fb34a6d` |
| 호출 시간 | `10919.9ms` |
| referenced_documents | `4` |
| input_tokens | `1763` |
| output_tokens | `894` |
| provider | `cywell-llm` |
| model | `gemma-4-26b-a4b-it-awq-8bit` |

위 값은 endpoint URL과 token 값을 노출하지 않는다.

## 추가 회귀 확인

권한 확인 질문도 OpenShift 운영 질문으로 분류되어 OpenShift Lightspeed를 호출한다.

| 질문 | answer_source | OpenShift Lightspeed status | Viewer path | related link |
|---|---|---|---|---|
| `사용자 권한은 어떤 명령으로 확인해?` | `lightspeed_with_pbs_rag` | `used` | `/external/lightspeed/53ab1ab5c718090f0417` | `OpenShift Lightspeed 공식 답변` |

## 증명 파일

| 파일 | 용도 | 확인할 값 |
|---|---|---|
| `artifacts/runtime/lightspeed_calls.jsonl` | OpenShift Lightspeed 호출 감사 로그 | `record_kind`, `status`, `badge_applied`, `conversation_id`, `viewer_path`, 입출력 토큰 사용량 |
| `artifacts/external_answers/lightspeed/0e7ac188f8aaa4499c8b.json` | OpenShift Lightspeed 응답 원문 artifact | `schema`, `provider`, `answer`, `conversation_id`, `referenced_documents` |
| `artifacts/runtime/chat_turns.jsonl` | PBS 질문/답변 처리 감사 로그 | `answer_source`, `pipeline_trace.external_answer`, `related_links` |
| `artifacts/answering/answer_log.jsonl` | 답변 파이프라인 실행 로그 | `openshift_lightspeed` trace, retrieval trace, final answer |
| PostgreSQL chat history metadata | 화면 히스토리 복원 근거 | `answer_source`, `external_answer`, `primary_boundary_badge` |

`lightspeed_calls.jsonl` 최신 로그 예시:

```json
{
  "record_kind": "openshift_lightspeed_call_audit",
  "session_id": "report-proof-lightspeed-latest",
  "answer_source": "lightspeed_with_pbs_rag",
  "status": "used",
  "badge_applied": true,
  "related_link_present": true,
  "viewer_path": "/external/lightspeed/0e7ac188f8aaa4499c8b",
  "artifact_id": "0e7ac188f8aaa4499c8b",
  "conversation_id": "a7803818-bda7-4d5f-a508-4a7d1fb34a6d",
  "duration_ms": 10919.9,
  "referenced_documents": 4,
  "input_tokens": 1763,
  "output_tokens": 894,
  "primary_boundary_badge": "Lightspeed",
  "provider": "cywell-llm",
  "model": "gemma-4-26b-a4b-it-awq-8bit"
}
```

## 작성된 코드

| 파일 | 역할 |
|---|---|
| `src/play_book_studio/config/settings.py` | `OPENSHIFT_LIGHTSPEED_BASE_URL`, token, provider, model, timeout, TLS 설정 로드 |
| `src/play_book_studio/integrations/lightspeed.py` | OpenShift Lightspeed `/v1/query`, `/authorized` 호출 client |
| `src/play_book_studio/answering/answerer.py` | 운영 질문 판별 후 OpenShift Lightspeed를 먼저 호출하고 PBS RAG와 결합 |
| `src/play_book_studio/http/server_support.py` | 최종 `/api/chat`, `/api/chat/stream` payload에 `answer_source`, `related_links`, `primary_*` 값 반영 |
| `src/play_book_studio/http/server_chat.py` | 채팅 처리 후 `lightspeed_calls.jsonl`, DB metadata, chat audit 저장 |
| `src/play_book_studio/http/server_routes_viewer.py` | `/external/lightspeed/{artifact_id}` Viewer 문서 생성 |
| `apps/web/src/pages/workspace/WorkspaceAnswer.tsx` | `external_openshift_lightspeed` 값을 `Lightspeed` 배지로 표시 |
| `apps/web/src/pages/WorkspacePage.tsx` | stream 응답과 히스토리 복원 시 `answer_source`, badge, related link 유지 |

핵심 코드 위치:

| 기능 | 위치 |
|---|---|
| 운영 질문 판별 | `src/play_book_studio/integrations/lightspeed.py:112` |
| API client | `src/play_book_studio/integrations/lightspeed.py:116` |
| `/v1/query` 호출 | `src/play_book_studio/integrations/lightspeed.py:181` |
| OpenShift Lightspeed 호출 분기 | `src/play_book_studio/answering/answerer.py:680` |
| OpenShift Lightspeed 호출 후 PBS RAG 검색 | `src/play_book_studio/answering/answerer.py:1021` |
| OpenShift Lightspeed 답변을 최종 프롬프트에 반영 | `src/play_book_studio/answering/answerer.py:1328` |
| Lightspeed 응답 artifact 저장 | `src/play_book_studio/answering/answerer.py:815` |
| related link 생성 | `src/play_book_studio/http/server_support.py:120` |
| 배지 판정값 생성 | `src/play_book_studio/http/server_support.py:141` |
| 감사 로그 저장 | `src/play_book_studio/http/server_chat.py:296` |
| 감사 로그 경로 | `src/play_book_studio/config/settings_paths.py:376` |
| Viewer artifact 로드 | `src/play_book_studio/http/server_routes_viewer.py:120` |
| Viewer HTML 생성 | `src/play_book_studio/http/server_routes_viewer.py:132` |
| 프론트 배지 표시 | `apps/web/src/pages/workspace/WorkspaceAnswer.tsx:105` |

## 질문 처리 흐름

1. 사용자가 PBS 챗봇에 OpenShift 운영 질문을 입력한다.
2. PBS Backend가 질문을 `/api/chat` 또는 `/api/chat/stream`으로 받는다.
3. `ChatAnswerer`가 OpenShift 운영 질문 여부를 판별한다.
4. 운영 질문이면 OpenShift Lightspeed `/v1/query`를 먼저 호출한다.
5. OpenShift Lightspeed 응답이 성공하면 `status=used`로 기록한다.
6. OpenShift Lightspeed 답변은 공식 기준 답변으로 프롬프트에 들어간다.
7. PBS RAG가 같은 질문으로 고객사 문서, 사내 문서, 사용자 업로드 문서, 공식 문서에서 근거를 찾는다.
8. PBS LLM이 OpenShift Lightspeed 답변과 PBS RAG 근거를 함께 사용해 최종 답변을 생성한다.
9. 최종 citation은 PBS 문서와 chunk 기준으로 만든다.
10. OpenShift Lightspeed 응답은 별도 artifact로 저장하고 Viewer 경로를 만든다.
11. 최종 payload에 `answer_source=lightspeed_with_pbs_rag`를 넣는다.
12. `related_links` 첫 항목에 OpenShift Lightspeed Viewer link를 넣는다.
13. 화면은 `answer_source`와 `boundary_truth`를 기준으로 `Lightspeed` 배지를 표시한다.
14. `lightspeed_calls.jsonl`, `chat_turns.jsonl`, `answer_log.jsonl`, DB metadata에 같은 사실을 남긴다.

## 배지 판정 기준

`Lightspeed` 배지는 다음 조건을 모두 만족할 때만 표시한다.

| 조건 | 의미 |
|---|---|
| `answer_source == lightspeed_with_pbs_rag` | 최종 답변 생성에 OpenShift Lightspeed가 사용됨 |
| `external_answer.status == used` | OpenShift Lightspeed 호출이 성공함 |
| `viewer_path` 존재 | OpenShift Lightspeed 응답 artifact가 저장됨 |
| `related_link_present == true` | 화면에서 열 수 있는 Viewer link가 생성됨 |

호출 실패, timeout, 미설정 상태에서는 `answer_source=pbs_rag`로 남고 `Lightspeed` 배지는 붙지 않는다.

## 검증 명령

헬스 확인:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8765/api/health |
  Select-Object -ExpandProperty runtime |
  Select-Object -ExpandProperty openshift_lightspeed
```

실제 채팅 호출 확인:

```powershell
docker compose exec app python -m play_book_studio.cli lightspeed-chat-smoke `
  --ui-base-url http://127.0.0.1:8765 `
  --session-id report-proof-lightspeed-smoke
```

통합 확인:

```powershell
docker compose exec app python -m play_book_studio.cli lightspeed-integration-smoke `
  --root-dir /app `
  --ui-base-url http://127.0.0.1:8765 `
  --session-id report-proof-lightspeed-integration
```

최신 감사 로그 확인:

```powershell
Get-Content artifacts/runtime/lightspeed_calls.jsonl -Tail 1
```

Viewer artifact 확인:

```powershell
Get-Content artifacts/external_answers/lightspeed/0e7ac188f8aaa4499c8b.json
```

## 테스트 근거

| 테스트 | 확인 내용 |
|---|---|
| `tests/test_lightspeed_client.py` | endpoint, provider/model, 인증 header 포함 여부, `/authorized`, `/v1/query`, smoke command |
| `tests/test_answerer_llm_final.py` | OpenShift Lightspeed가 PBS RAG보다 먼저 호출되고 최종 답변 재료로 사용됨 |
| `tests/test_app_server.py` | `/api/chat`, `/api/chat/stream` payload에 `answer_source`, `Lightspeed` related link, 감사 로그가 남음 |
| `tests/test_lightspeed_viewer.py` | OpenShift Lightspeed 응답 artifact가 PBS Viewer에서 열림 |
| `apps/web/src/pages/workspace/WorkspaceAnswer.test.tsx` | 프론트 배지가 `Lightspeed`로 표시됨 |

최근 검증 결과:

| 검증 | 결과 |
|---|---|
| `pytest tests/test_app_server.py tests/test_answerer_llm_final.py tests/test_lightspeed_client.py tests/test_lightspeed_viewer.py -q` | `37 passed` |
| `npm --prefix apps/web exec vitest run src/pages/workspace/WorkspaceAnswer.test.tsx` | `1 file passed`, `2 tests passed` |
| `npm --prefix apps/web run build` | pass |
| `git diff --check` | pass |
| `docker compose ps` | `app`, `postgres`, `web` healthy |
| `/api/viewer-document?viewer_path=/external/lightspeed/0e7ac188f8aaa4499c8b` | `200`, code block 렌더링, raw bold marker 없음 |

## 보고 문장

PBS는 OpenShift 운영 질문을 받으면 OpenShift Lightspeed API를 호출한다. 호출이 성공한 경우에만 `answer_source=lightspeed_with_pbs_rag`와 `external_answer.status=used`가 기록되고, 이 상태에서만 화면에 `Lightspeed` 배지가 표시된다. OpenShift Lightspeed 응답은 `artifacts/external_answers/lightspeed/{artifact_id}.json`으로 저장되며, PBS Viewer의 `/external/lightspeed/{artifact_id}` 경로에서 확인할 수 있다. 따라서 화면의 `Lightspeed` 배지는 단순 표시가 아니라 실제 API 호출, 응답 저장, Viewer 연결까지 완료된 상태를 의미한다.
