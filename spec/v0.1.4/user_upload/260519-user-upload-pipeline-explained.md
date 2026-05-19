# 유저 업로드 문서가 챗봇에 반영되기까지 — 단계별 작동 원리

작성일: 2026-05-19
대상 경로: `/playbook-library/repository` 의 User Document Pipeline
관련 코드:
- 백엔드 파이프라인: `src/play_book_studio/http/upload_api.py`
- 파싱: `src/play_book_studio/ingestion/document_parsing.py`
- DB 저장: `src/play_book_studio/db/document_repository.py`
- Qdrant 인덱싱: `src/play_book_studio/db/qdrant_indexer.py`
- 챗봇 검색: `src/play_book_studio/retrieval/`

---

## 0. 한눈에 보는 전체 흐름

```
[사용자 PDF]
   │
   ▼
①  원본 저장    →  바이트를 디스크에 그대로 보관
   │
   ▼
②  문서 파싱    →  PDF → markdown → block 단위로 분해
   │
   ▼
③  청크 생성    →  block들을 1800자 단위로 묶어 검색 단위 chunk 만들기
   │
   ▼
④  DB 저장     →  PostgreSQL에 문서/청크/스코프 라벨(owner_user_id 등) 기록
   │
   ▼
⑤  Qdrant 인덱싱 →  각 chunk를 임베딩 벡터로 변환 → 벡터 DB에 upsert
   │
   ▼
[챗봇이 질문을 받으면]
   질문 임베딩 → Qdrant에서 유사 chunk 검색 + BM25(키워드) 보강
   → owner_user_id 필터로 본인 문서만 추림
   → 그 chunk들을 LLM 컨텍스트에 넣고 답변 생성
```

업로드 단계는 5개, 챗봇 단계는 그 결과를 그대로 쓰는 구조입니다. "8단계"라고 부르던 received/scope/ready는 시스템 단계가 아니라 단순 마커였어요.

---

## ① 원본 저장 (store)

**하는 일**

- 브라우저가 multipart로 보낸 파일 바이트를 디스크에 그대로 저장
- 저장 경로: `<object_storage_dir>/uploads/sources/<upload_id>/<filename>`
- `upload_id` 는 UUID. 같은 파일을 두 번 올려도 충돌 없음
- 파일명은 `[A-Za-z0-9._-]` 외 문자 정제

**왜 따로 저장?**

- 파싱이 실패해도 원본은 남기기 위해
- 나중에 "원본 미리보기" 기능에서 같은 파일을 다시 보여주기 위해
- 디버깅 — 어떤 PDF가 어떻게 들어왔는지 추적

**걸리는 시간**: 수 ~ 수십 ms (파일 크기에 비례)

**코드**: `_store_uploaded_file()` in `upload_api.py`

---

## ② 문서 파싱 (parse)

**하는 일**

- 파일 확장자 감지 (PDF/DOCX/PPTX/XLSX/MD/TXT/이미지 등)
- markitdown 라이브러리로 **markdown 문자열로 변환**
- markdown을 다시 잘라서 **block** 단위로 분해
  - block = 헤딩 / 단락 / 표 / 리스트 / 이미지 같은 의미 단위
- 이미지/표 같은 asset 별도 수집 (Qwen 비전 모델로 캡션 생성 가능)
- SHA256, mime_type, 페이지 추정 정보를 메타데이터로 부착

**왜 markdown으로?**

- PDF/DOCX/PPTX는 내부 구조가 제각각이라 직접 다루기 어렵움
- markdown은 LLM이 가장 잘 이해하는 텍스트 포맷
- "헤딩 → 단락" 구조가 보존되므로 청크 단계에서 의미 단위로 자르기 좋음

**실패 패턴**

- 스캔본 PDF(이미지로만 구성) → 텍스트 0개 → block 없음 → 파이프라인 중단
- 암호화 PDF → 파서가 빈 결과 반환
- 손상된 파일 → markitdown 예외

**걸리는 시간**: PDF 기준 수십 ms ~ 수 초 (페이지 수에 비례)

**핵심 산출물**: `ParsedUploadDocument(blocks, assets, markdown, warnings, ...)`

**코드**: `parse_upload_document()` in `document_parsing.py:213`

---

## ③ 청크 생성 (chunk)

**하는 일**

- block들을 합쳐서 약 1800자 단위의 **chunk** 로 묶음
- 같은 섹션 안에서만 묶도록 헤딩 경계 존중
- 청크 간 약간 overlap (기본 1 block) — 검색 시 경계에서 정보 누락 방지
- 각 chunk에 `section_path`(어느 챕터/섹션에서 왔는지) 기록

**왜 자르는가?**

- 임베딩 모델은 입력 길이 제한이 있음 (보통 8192 토큰)
- 너무 큰 chunk는 검색 정밀도가 떨어짐 ("이 chunk 안 어디에 답이 있는지" 흐려짐)
- 너무 작은 chunk는 문맥이 끊김
- 1800자가 절충점

**왜 overlap?**

- 답이 청크 경계에 걸쳐 있으면 검색이 둘 다 놓침
- 한 block씩 겹쳐서 그 위험을 줄임

**걸리는 시간**: 보통 수 ms

**핵심 산출물**: `tuple[DocumentChunk, ...]` — 각 chunk는 검색용 text + section_path + 메타데이터

**코드**: `build_document_chunks()` in `document_parsing.py:321`

---

## ④ DB 저장 (persist)

**하는 일**

PostgreSQL의 여러 테이블에 한 트랜잭션으로 기록:

| 테이블 | 기록 내용 |
|---|---|
| `document_sources` | 원본 파일 메타 (filename, sha256, storage_key, **owner_user_id**, **visibility**, **source_scope**, repository_id) |
| `document_versions` | 같은 문서가 재업로드될 때 버전 |
| `parse_jobs` | 파싱 작업 기록, status |
| `parsed_documents` | 파싱 산출물 메타 |
| `document_blocks` | 파싱한 block들 (text + 위치 정보) |
| `document_chunks` | chunk text + section_path + **owner_user_id 라벨 동일 복사** |
| `document_assets` | 표/이미지 별도 저장 |

**가장 중요한 점 — 스코프 라벨링**

`owner_user_id`, `visibility`, `source_scope` 세 컬럼이 **chunk 행에까지 같이** 복사됩니다.

- `owner_user_id`: 업로드한 사용자 (X-User 헤더로 자동)
- `visibility`: `private_user` / `workspace_shared` / `global_shared` 중 하나
  - 사용자 업로드는 기본 `private_user` (created_by 가 있으면)
- `source_scope`: `user_upload` (공식문서면 `official_*`)

이 라벨들이 ⑤번에서 Qdrant payload에도 같이 들어가고, 챗봇이 검색할 때 **WHERE 필터**로 사용됩니다. 즉 "세션별로 분리" 가 별도 DB가 아니라 **컬럼 한 줄로** 구현된 것.

**실패 패턴**

- DATABASE_URL 누락 → 400
- PK 충돌 (같은 sha256 재업로드) → 중복 감지 후 기존 row 재사용

**걸리는 시간**: 청크 수에 비례, 수십 ms ~ 수백 ms

**코드**: `persist_parsed_upload_document()` in `db/document_repository.py`

---

## ⑤ Qdrant 인덱싱 (index)

**하는 일**

1. 각 chunk text를 **임베딩 모델**(외부 API)에 보내서 **벡터(보통 1024~3072차원)** 로 변환
2. 그 벡터를 Qdrant 컬렉션에 upsert
3. payload에 chunk의 메타데이터(owner_user_id, visibility, source_scope, document_source_id, repository_id, section_path 등) 같이 저장
4. PostgreSQL의 `qdrant_index_entries` 테이블에 "이 chunk는 Qdrant에 들어갔다" 기록

**왜 두 군데에?**

- PostgreSQL: text와 메타 원본을 가진 진실 (BM25 키워드 검색에도 사용)
- Qdrant: **의미 기반 검색** 전용. "전세 보증금" 으로 물어도 "임대차 보증금" 청크 찾음

**임베딩이란?**

- 텍스트를 고차원 벡터로 바꾸는 모델 출력
- 의미가 비슷한 텍스트는 벡터 공간에서 가까운 위치
- 코사인 유사도로 "가까운 chunk" 빠르게 검색 가능

**걸리는 시간**: 임베딩 API 응답 시간이 대부분 차지. 청크 수에 비례. 보통 수백 ms ~ 수 초.

**실패 패턴**

- 임베딩 API 키 미설정/오류 → 일부 청크 누락
- Qdrant 연결 실패 → indexed_count = 0
- 응답에 `candidate_count` vs `indexed_count` 차이가 있으면 일부 실패

**코드**: `index_pending_document_chunks()` in `db/qdrant_indexer.py`

---

## 챗봇이 이 데이터를 어떻게 쓰는가

업로드가 끝난 후, 사용자가 채팅창에 질문을 입력하면:

### 1) 검색 (Retrieval)

`src/play_book_studio/retrieval/retriever_pipeline.py`

- 질문을 같은 임베딩 모델로 벡터화
- **Qdrant 검색** (vector): 코사인 유사도 top-N (보통 20~50)
- **PostgreSQL BM25 검색** (keyword): tsvector 기반 키워드 매칭
- 두 결과 합쳐서 **하이브리드 랭킹**

### 2) 스코프 필터링 (Access Scope)

`retrieval/access_scope.py`

검색 결과 각 hit에 대해:

```python
if visibility in {"global_shared", "workspace_shared"}:
    pass  # 모두에게 공개 → 통과
elif visibility == "private_user":
    if hit.owner_user_id != context.owner_user_id:
        drop  # 다른 사용자 문서 → 차단
```

즉 **본인의 private_user 문서 + 워크스페이스 공유 문서 + 공식 문서**가 통과.

### 3) 컨텍스트 구성

- 통과한 chunk들의 text를 LLM 프롬프트에 첨부
- "다음 문맥을 참고해서 답하라" 형태로 시스템 메시지 구성
- LLM이 답변 생성 시 그 chunk를 인용 (chunk_id 추적)

### 4) 응답에 인용 정보 포함

- 답변에 `[1]`, `[2]` 마커
- 마커별로 어떤 chunk(어떤 문서의 어떤 섹션)에서 왔는지 함께 반환
- 프런트가 "출처: 계약서.pdf p.3" 식으로 표시

---

## 핵심 인사이트

### 공식문서 vs 사용자문서 차이

| | 공식문서 | 사용자 문서 |
|---|---|---|
| 파싱 | 같은 markitdown | 같은 markitdown |
| 청킹 | 같은 build_document_chunks | 같은 build_document_chunks |
| 임베딩 | 같은 모델 | 같은 모델 |
| Qdrant 저장 | 같은 컬렉션 | 같은 컬렉션 |
| 검색 | 같은 retriever | 같은 retriever |
| **차이는 단 하나** | `visibility = global_shared` | `visibility = private_user` |

**구조화 정도 차이는 검색 가능성이 아니라 인용 품질에 영향**. 임베딩 모델은 자유 텍스트도 벡터로 잘 만들고, 검색은 그 벡터 기반이라 작동합니다. 다만 공식문서는 챕터/페이지 메타가 풍부해서 인용이 깔끔하고, 사용자 PDF는 그게 빈약해서 "p.3 두 번째 단락" 수준에 그칩니다.

### 세션별 격리 메커니즘

- DB는 한 곳 (PostgreSQL + Qdrant 한 컬렉션)
- 모든 chunk row에 `owner_user_id` 컬럼이 박혀있음
- 챗봇 검색이 그 컬럼을 WHERE 필터로 사용
- → 1만 명 사용자 = 1만 개 DB가 아니라, 한 DB + 라벨 한 컬럼

### 마이그레이션 필요한가?

이미 스코프 컬럼은 마이그레이션 `0004_repository_session_scope.sql` / `0009_qdrant_payload_contract.sql` 로 도입 완료. **새 마이그레이션 필요 없음.** 작업은 "이미 있는 컬럼에 올바른 값이 들어가게 + 올바르게 필터링되는지" 검증이 전부.

---

## 단계별 ms 로그 해석 가이드

UI에 단계별로 ms가 표시됩니다. 정상 범위:

| 단계 | 정상 범위 | 비정상이면 의심할 것 |
|---|---|---|
| 원본 저장 | < 100ms | 디스크 IO/권한 |
| 문서 파싱 | 100ms ~ 수 초 | 매우 큼: 페이지 많음 / 0ms 근처: 빈 결과 의심 |
| 청크 생성 | < 50ms | block이 많으면 살짝 늘어남, 정상 |
| DB 저장 | 50ms ~ 수백 ms | DB 연결 / 트랜잭션 |
| Qdrant 인덱싱 | 수백 ms ~ 수 초 | 임베딩 API 지연 |

전체 합이 **1초 미만**이면 거의 확실히 어느 단계가 빈 결과를 만든 것. 정상 PDF는 합쳐서 2~10초.

---

## 잘못되면 어디를 봐야 하나

| 증상 | 어디 보면 됨 |
|---|---|
| 파싱이 0ms로 끝남 | 파일이 스캔본/암호화. ② 파서가 빈 결과 |
| chunk_count = 0 | ② 결과 비었거나 ③ 청커가 navigation-only로 다 걸러냄 |
| indexed_count < candidate_count | 임베딩 API 일부 실패. ⑤ |
| 5단계 다 초록인데 챗봇이 못 씀 | 스코프 미스매치. visibility/owner_user_id 라벨 확인 |
| 다른 사용자가 내 문서 봄 | visibility 잘못 설정 (workspace_shared 되어있을 가능성) |

---

## 결론

업로드는 5단계 동기 파이프라인입니다. 각 단계는 독립적인 일을 하고, 한 단계라도 비면 다음이 의미 없어요. 챗봇은 5단계가 모두 끝난 상태(PostgreSQL+Qdrant 양쪽 다 들어간 chunk)에서만 검색합니다.

"세션별 격리" 도 새 시스템이 아니라 chunk 행에 박힌 `owner_user_id` 한 컬럼이 전부. 그래서 마이그레이션 없이, 인프라 추가 없이, 사용자별 RAG가 동작합니다.
