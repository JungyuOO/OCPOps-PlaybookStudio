# .kugnus-plan 안내

## 참고 우선순위

| 문서 | 용도 | 상태 |
|---|---|---|
| `lightspeed-call-proof-report.md` | OpenShift Lightspeed API 호출 증명, 로그, 코드, 질문 처리 흐름 보고용 산출물 | 최신 |
| `lightspeed-pbs-chat-integration.md` | OpenShift Lightspeed PBS Chat 연동 구조와 검증 절차 | 최신 |
| `company-openshift-lightspeed-next.md` | 회사 OCP OpenShift Lightspeed 연동 전 확인 항목 | 최신 |
| `pgvector-change-summary.md` | PostgreSQL + pgvector 전환 변경 요약 | 최신 |
| `pgvector-acceptance-check.md` | 수용 기준별 증거 점검 | 최신 |
| `pgvector-transition-handoff.md` | 실행, 검증, handoff 기록 | 최신 |
| `change-inventory.md` | 변경 파일 영역별 목록 | 최신 |
| `macbook-crc-lightspeed-runbook.md` | MacBook CRC 실험 실행 절차 | 다음 단계 |
| `rag-foundation/05-go-no-go.md` | RAG gate 최종 판정 | 최신 |
| `rag-foundation/*.md` | chunk, embedding, retrieval, viewer audit 상세 | 최신 |
| `pbs-enhancement-plan.md` | PBS 기능별 고도화 계획 | 참고 |
| `plan1.md` | 초기 기능별 작업 계획 | 참고 |

## 현재 판정

| 항목 | 값 |
|---|---|
| runtime | PostgreSQL + pgvector |
| running services | `app`, `postgres`, `web` |
| OpenShift Lightspeed | MacBook endpoint 기준 실제 통합 smoke 성공 |
| OpenShift Lightspeed provider | `cywell-llm` |
| OpenShift Lightspeed model | `gemma-4-26b-a4b-it-awq-8bit` |
| OpenShift Lightspeed TLS | self-signed chain으로 로컬 검증 시 TLS 검증 우회 |
| OpenShift Lightspeed mock | auth, query, chat, source-meta, Viewer 통합 smoke 성공 |
| RAG gate | `13/13 pass`, `decision=go` |
| answer/viewer audit | `8 checks pass` |
| Lightspeed 핵심 Python tests | `37 passed` |
| WorkspaceAnswer Web test | `2 passed` |
| Web build | pass |

## 주의

`rag-foundation/*.json`은 재현 증거용 상세 결과이며 chunk preview를 포함할 수 있다. Git 추적 대상에서는 제외하고, 요약 보고에는 `05-go-no-go.md`, `pgvector-change-summary.md`, `pgvector-acceptance-check.md`를 우선 사용한다.

## 커밋 기준

| 구분 | 처리 |
|---|---|
| 포함 | source, migration, deploy, test, 요약 markdown 근거 |
| 포함 | `rag-foundation/*.md`, `pgvector-*.md`, `lightspeed-pbs-chat-integration.md`, `company-openshift-lightspeed-next.md`, `macbook-crc-lightspeed-runbook.md` |
| 제외 | `rag-foundation/*.json` 상세 감사 결과 |
| 제외 | Docker volume, build output, local tunnel, local secret, local endpoint 값 |
| 주의 | endpoint/token 값은 문서와 Git 추적 대상에 남기지 않는다 |
