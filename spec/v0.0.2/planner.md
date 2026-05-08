# v0.0.2 — Learning Metadata Ref Graph & Wiki Viewer Assets

## 목표

v0.0.2의 1순위 목표는 OCP 공식 문서를 단순 검색용 chunk 묶음이 아니라 **단계별 학습 가이드로 연결 가능한 문서 그래프**로 만드는 것이다.

사용자는 Wiki/Library에서 특정 문서를 선택해 Studio Chat으로 이동할 수 있고, Studio는 해당 문서 범위로 RAG를 수행한다. v0.0.2에서는 이 흐름을 더 자연스럽게 만든다.

- 문서 scope를 Studio에서 명확히 해제할 수 있어야 한다.
- 각 공식 문서는 metadata/ref 기반으로 이전/다음 학습 단계와 관련 문서를 가져야 한다.
- RAG 답변은 현재 문서뿐 아니라 metadata의 다음 ref를 활용해 "다음에 볼 문서/다음 실습 단계"를 제안할 수 있어야 한다.
- Wiki Viewer에 표시되는 이미지/figure asset 오류를 해결한다.

---

## 범위

### Core (P0 — v0.0.2 릴리스 기준)

- [x] Studio document scope 해제 UX 수정
- [ ] Wiki/Library → Studio document scope 상태 전달 재검증
- [ ] 공식 문서 metadata/ref 모델 설계
- [ ] `document_sources.metadata` / `document_chunks.metadata`에 들어갈 learning ref schema 정의
- [ ] official/study import 시 ref metadata를 채울 수 있는 최소 구현
- [ ] RAG citation/answer context에서 current/next/related ref metadata를 사용할 수 있는 경계 추가
- [ ] Library 문서 카드 또는 Studio scoped 상태바에 다음 학습 문서 후보 표시 구조 추가
- [x] Wiki Viewer 이미지/figure asset 미표시 오류 원인 분석
- [x] Wiki Viewer 이미지 URL/asset resolver 수정
- [x] metadata/ref 및 image resolver focused test 추가
- [x] frontend production build
- [x] backend focused test

### Extras (P1 — 여유 있으면 포함)

- [ ] "다음 단계로 이동" 버튼을 Studio scope 상태바 또는 citation preview에 추가
- [ ] 문서 관계 그래프를 Library sidebar category 진행 상태로 표시
- [ ] beginner/intermediate/admin persona별 learning order 분리
- [ ] command/lab task metadata와 문서 ref 연결
- [ ] image asset에 Qwen VLM description을 viewer caption 또는 alt로 노출

### 비범위 (v0.0.3 이후로 연기)

- 완전한 course authoring UI
- LLM이 자동으로 전체 커리큘럼을 생성하는 기능
- pgvector 전환
- full multi-user auth/permission admin
- HWP/HWPX/HWPML 지원
- Wiki relation graph 시각화

---

## 배경

현재 v0.0.1까지는 문서 scope RAG 자체가 동작하도록 고정했다. 하지만 초보 사용자에게 "공식 문서 기반 단계별 학습" 경험을 제공하려면 chunk 검색만으로는 부족하다.

필요한 것은 검색 품질뿐 아니라 **문서 간 학습 순서와 참조 관계를 metadata로 저장하는 것**이다.

| 현재 | v0.0.2 목표 |
|---|---|
| document_source_id 기준 scope RAG | scope 문서의 다음 학습 ref까지 알 수 있음 |
| toc_path, section_number 보존 | learning_path, prerequisite, next_ref, related_ref 보존 |
| Library 문서 선택 → Studio 이동 | Studio에서 scope 해제/다음 문서 이동 가능 |
| Wiki Viewer figure 일부 미표시 | DB/runtime asset resolver로 이미지 표시 안정화 |

---

## Metadata 설계 방향

### 현재 구현 메모

- Studio scope 상태바의 문서 해제 버튼을 텍스트가 있는 버튼으로 변경했다.
- `/api/runtime-figures`는 삭제된 root `data/wiki_relations/figure_assets.json`를 직접 읽지 않고 기존 Wiki relation loader를 사용한다.
- figure asset에 `viewer_path`가 비어 있어도 asset filename 기반 `/wiki/figures/{book_slug}/{asset}/index.html` 경로를 생성한다.
- 검증: `python -m pytest tests\test_runtime_figures_api.py tests\test_answer_context_metadata.py`, `npm --prefix apps/web run build`.

### Document-level metadata

`document_sources.metadata` 또는 official import source metadata에 다음 구조를 추가한다.

```json
{
  "book_slug": "installation_overview",
  "book_title": "Installing OpenShift Container Platform",
  "category_key": "install",
  "category_label": "Install",
  "learning": {
    "track": "ocp-foundation",
    "stage_id": "install-01",
    "stage_order": 10,
    "difficulty": "beginner",
    "persona": ["beginner", "platform-admin"],
    "estimated_minutes": 20,
    "prerequisite_refs": [
      {
        "ref_type": "document",
        "book_slug": "overview",
        "reason": "클러스터 구성 요소 개념 선행"
      }
    ],
    "next_refs": [
      {
        "ref_type": "document",
        "book_slug": "nodes",
        "reason": "설치 후 노드 상태 확인으로 이어짐"
      }
    ],
    "related_refs": [
      {
        "ref_type": "document",
        "book_slug": "networking_overview",
        "relation": "supports",
        "reason": "설치 중 네트워크 요구사항 확인"
      }
    ],
    "lab_refs": [
      {
        "ref_type": "lab_task",
        "lab_task_id": "verify-cluster-operators",
        "command_hint": "oc get co"
      }
    ]
  }
}
```

### Chunk-level metadata

`document_chunks.metadata`에는 문서 전체 관계보다 더 세밀한 section/step 힌트를 둔다.

```json
{
  "learning": {
    "section_role": "concept | procedure | verification | troubleshooting | reference",
    "step_order": 3,
    "user_goal": "클러스터 설치 후 operator 상태 확인",
    "command_hints": ["oc get co", "oc get nodes"],
    "next_section_anchor": "checking-cluster-operators",
    "related_section_refs": [
      {
        "book_slug": "operators",
        "source_anchor": "cluster-operators",
        "relation": "deep-dive"
      }
    ]
  }
}
```

### Ref 타입

```text
document        다른 공식/study/user 문서
section         특정 문서의 source_anchor/toc section
lab_task        실습 task
command_check   명령어 검증 항목
asset           figure/image/table asset
external        외부 URL
```

### Relation 타입

```text
prerequisite    먼저 알아야 함
next            다음 학습 단계
related         같이 보면 좋음
deep-dive       심화 설명
troubleshoots   문제 해결 경로
verifies        실습 검증 경로
uses            명령/리소스를 사용
```

---

## DB/Runtime 반영 방향

### 1차 구현

DB schema를 바로 늘리기보다 기존 JSON metadata를 활용한다.

- `document_sources.metadata.learning`
- `document_chunks.metadata.learning`
- `parsed_documents.metadata.learning`

장점:

- migration 리스크가 낮다.
- official/study 재import 없이 일부 metadata backfill이 가능하다.
- RAG context/citation에 바로 흘릴 수 있다.

### 2차 후보

관계 질의가 많아지면 별도 table로 분리한다.

```sql
document_learning_refs (
    id uuid primary key,
    source_document_id uuid not null,
    source_chunk_id uuid,
    relation_type text not null,
    target_ref_type text not null,
    target_document_id uuid,
    target_book_slug text,
    target_source_anchor text,
    target_lab_task_id uuid,
    reason text,
    metadata jsonb not null default '{}',
    created_at timestamptz not null default now()
)
```

v0.0.2에서는 JSON metadata 우선, table은 설계 후보로만 둔다.

---

## 구현 계획

### Step 1. Studio Scope 해제 UX

- 현재 document scope 상태바에 해제 버튼이 보이지만 사용자가 발견하기 어렵거나 동작 범위가 부족하다.
- 개선:
  - 버튼 title/copy를 명확하게 변경
  - document scope 해제 시 `active_document_id`, `active_document_title`, `active_category_key`, `active_category_label` 모두 제거
  - repository scope까지 해제하는 별도 동작이 필요한지 검토
  - 상태바에 `문서 범위 해제` 텍스트 버튼 또는 x icon tooltip 추가

### Step 2. Metadata Ref Schema 고정

- `spec/v0.0.2/planner.md`의 schema를 기준으로 backend helper를 만든다.
- 후보 모듈:
  - `src/play_book_studio/ingestion/learning_metadata.py`
  - `src/play_book_studio/db/official_documents.py`
  - `src/play_book_studio/db/document_repository.py`
- 목표:
  - category/document metadata에서 learning refs를 안전하게 읽는 parser
  - 잘못된 metadata가 있어도 RAG runtime이 죽지 않도록 normalize

### Step 3. Official/Study Metadata Backfill

- `book_slug`, `category_key`, `toc_path`, `source_anchor` 기반으로 최소 next/prerequisite을 생성한다.
- 초기 규칙 예:

```text
overview -> installation_overview -> nodes -> operators -> networking_overview -> storage -> monitoring -> troubleshooting
```

- 이 규칙은 하드코딩 답변이 아니라 metadata seed/backfill 규칙으로만 사용한다.
- 답변 내용은 여전히 RAG retrieved chunks 기반이어야 한다.

### Step 4. RAG Context에 Learning Ref 노출

- citation 또는 retrieval trace에 다음 정보를 포함한다.
  - current_document_learning_stage
  - prerequisite_refs
  - next_refs
  - related_refs
  - lab_refs
- LLM prompt에는 "다음 학습 추천"을 위한 structured context로 제공한다.
- chunk 본문에 ref metadata를 섞지 않는다.

### Step 5. Library/Studio UI에 다음 문서 후보 표시

- Studio scoped 상태바 또는 answer evidence preview에 다음 문서 후보를 표시한다.
- 클릭 시 해당 문서로 scope를 바꿔 Studio Chat을 유지한다.
- Library sidebar에는 현재 category/document의 active 상태와 다음 후보를 표시할 수 있는 구조만 먼저 둔다.

### Step 6. Wiki Viewer 이미지 오류 분석

확인할 구현 위치:

- `src/play_book_studio/http/viewer_page_sections.py`
- `src/play_book_studio/http/viewer_blocks_rich.py`
- `src/play_book_studio/http/wiki_relations.py`
- `src/play_book_studio/http/wiki_user_overlay_targets.py`
- `apps/web/src/pages/workspace/WorkspaceViewerPanel.tsx`
- `apps/web/src/lib/runtimeApi.ts`

점검 항목:

- figure asset URL이 실제 route로 resolve되는지
- `/wiki/figures/...` 또는 `/playbooks/...` 경로가 backend에서 서빙되는지
- DB-backed runtime에서 `figure_assets.json` fallback을 못 읽는지
- image filename/asset_name normalization이 맞는지
- viewer HTML 안의 `<img src>`가 상대경로/절대경로를 잘못 쓰는지
- browser console/network에서 404/500이 나는지

### Step 7. Image Resolver 수정

- figure asset lookup은 우선 DB/runtime metadata를 보고, 없으면 relation asset fallback을 본다.
- 이미지가 없을 때는 깨진 이미지 대신 caption/alt fallback을 보여준다.
- Qwen VLM description이 있으면 alt/caption fallback으로 사용할 수 있다.

---

## API 후보

가능하면 기존 API를 확장한다.

| API | 목적 |
|---|---|
| `/api/repositories/documents` | document metadata에 learning refs 포함 |
| `/api/viewer-document` | viewer payload에 image/ref metadata 포함 |
| `/api/wiki-overlay-targets` | figure/section/document target resolve |
| `/api/chat` / `/api/chat/stream` | active document learning refs를 prompt context에 포함 |
| 신규 후보 `/api/documents/{id}/learning-refs` | 필요할 때만 추가 |

---

## 테스트 계획

### Backend

```powershell
python -m pytest tests/test_learning_metadata.py
python -m pytest tests/test_document_repository.py
python -m pytest tests/test_answer_context_metadata.py
python -m pytest tests/test_source_books_viewer_resolver.py
python -m pytest tests/test_ops_console_api.py
```

### Frontend

```powershell
npm --prefix apps/web run build
```

필요 시 focused UI test:

```text
Library Ask this document -> Workspace scoped status -> Clear scope
Workspace scoped status -> Next document candidate click
Wiki Viewer -> image renders or fallback text appears
```

### Smoke

```text
GET /api/repositories/documents
GET /api/viewer-document?...
GET /api/wiki-overlay-targets?...
Studio document-scoped chat
Wiki Viewer image network request
```

---

## 완료 기준 (DoD)

1. Studio에서 특정 문서 scope를 사용자가 명확히 해제할 수 있다.
2. document scope 해제 후 chat request에 `active_document_id`가 더 이상 포함되지 않는다.
3. 공식 문서 metadata에 최소 learning refs가 들어간다.
4. RAG context/citation/retrieval trace에서 learning refs를 읽을 수 있다.
5. 답변은 현재 문서 기반으로 하되, 다음 학습 문서 후보를 metadata 기반으로 제안할 수 있다.
6. ref metadata는 chunk 본문에 섞이지 않는다.
7. Wiki Viewer 이미지가 정상 표시된다.
8. 이미지가 없거나 asset resolve 실패 시 깨진 이미지 대신 fallback caption/alt가 표시된다.
9. backend focused tests가 통과한다.
10. frontend production build가 통과한다.

---

## 위험과 주의사항

- next step을 하드코딩 답변으로 만들면 안 된다. 하드코딩은 metadata seed/backfill까지만 허용한다.
- ref metadata는 RAG 검색/답변을 보조하는 구조화 신호이지, 답변 본문 자체가 아니다.
- private user upload의 learning refs는 owner scope를 지켜야 한다.
- official docs ref와 user private refs를 섞어 노출하지 않는다.
- Wiki Viewer image fallback이 root `data/`, `manifests/`, `tmp_source` runtime 의존을 되살리면 안 된다.
- HWP/HWPX/HWPML은 여전히 범위 밖이다.

---

## 작업 메모

- 2026-05-08: v0.0.1 완료 커밋 `33b5922` 이후 `feat/v0.0.2/metadata-ref-flow` 브랜치를 생성했다.
- 2026-05-08: v0.0.2의 1순위는 공식문서 단계형 RAG를 위한 metadata/ref 설계로 정한다.
