# .kugnus-plan 안내

## 참고 우선순위

| 문서 | 용도 | 상태 |
|---|---|---|
| `pgvector-change-summary.md` | PostgreSQL + pgvector 전환 변경 요약 | 최신 |
| `pgvector-acceptance-check.md` | 수용 기준별 증거 점검 | 최신 |
| `pgvector-transition-handoff.md` | 실행, 검증, handoff 기록 | 최신 |
| `change-inventory.md` | 변경 파일 영역별 목록 | 최신 |
| `company-openshift-lightspeed-next.md` | 회사 OCP OpenShift Lightspeed 연동 전 확인 항목 | 다음 단계 |
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
| RAG gate | `13/13 pass`, `decision=go` |
| answer/viewer audit | `8 checks pass` |
| Python tests | `568 passed`, `1 skipped` |
| Web tests | `16 passed` |
| Web build | pass |

## 주의

`rag-foundation/*.json`은 재현 증거용 상세 결과이며 chunk preview를 포함할 수 있다. Git 추적 대상에서는 제외하고, 요약 보고에는 `05-go-no-go.md`, `pgvector-change-summary.md`, `pgvector-acceptance-check.md`를 우선 사용한다.

## 커밋 기준

| 구분 | 처리 |
|---|---|
| 포함 | source, migration, deploy, test, 요약 markdown 근거 |
| 포함 | `rag-foundation/*.md`, `pgvector-*.md`, `company-openshift-lightspeed-next.md`, `macbook-crc-lightspeed-runbook.md` |
| 제외 | `rag-foundation/*.json` 상세 감사 결과 |
| 제외 | Docker volume, build output, local tunnel, local secret, local endpoint 값 |
| 주의 | 회사 OpenShift Lightspeed와 MacBook CRC는 다음 단계이며 현재 PBS RAG 수용 기준에는 포함하지 않는다 |
