# v0.1.4 Parsing Layer Schema

## 이 문서가 정의하는 것

Parsing layer는 "원본이 무엇이었고, parser가 무엇을 보았는지"를 보존하는 계층이다. 검색·답변에 쓰이지 않는다. 그 일은 corpus layer가 한다 (`spec/v0.1.4/db-corpus-schema.md`).

본 문서는 다음 6개 테이블을 정의한다.

| 테이블 | 한 줄 설명 |
| --- | --- |
| `document_sources` | 원본 파일이 어디서 왔는지 (URL, 업로드, 리포지토리, 컬렉션). |
| `document_versions` | 같은 원본의 변경 이력(불변 스냅샷). |
| `parse_jobs` | parser 실행 상태(큐·진행·실패). |
| `parsed_documents` | parser가 한 원본을 처리한 결과(문서 1개 단위). |
| `document_blocks` | 문서를 구조 단위로 쪼갠 결과(문단·코드·표·이미지·슬라이드 zone 등). |
| `document_assets` | 추출된 이미지·도표·첨부 파일과 그 OCR/캡션. |

이 6개는 JSON 공식문서, PPT-OCR 운영문서, 사용자 업로드 PDF 모두를 같은 모양으로 받는다. 어떤 원본이냐는 `source_kind` 컬럼 하나로 구분한다.

## 원본별 매핑 개요

| 원본 종류 | `source_kind` | 코드 매핑 | 어떻게 들어오나 |
| --- | --- | --- | --- |
| Red Hat 공식 docs (HTML single page) | `html_single` | 현재 코드의 `html-single` literal과 일대일 | parser가 manifest를 읽고 각 chunk를 `document_blocks` row로 매핑. |
| 공식 docs upstream 리포지토리 (asciidoc) | `source_repo` | 현재 코드의 `source-first` literal | repo clone → asciidoc parse → blocks. |
| 운영문서 PPT (slide_graph + OCR) | `pptx_ocr` | 신규 (course pipeline의 slide_graph 재사용) | 슬라이드별 zone을 `document_blocks`, attachment·OCR을 `document_assets`. |
| 사용자 업로드 PDF | `pdf_upload` | 신규 | 페이지·블록·표·이미지를 `document_blocks` + `document_assets`. |
| 사용자 업로드 PPTX | `pptx_upload` | 신규 | PPT 라인과 동일. |
| 사용자 업로드 markdown/txt | `markdown_upload` / `txt_upload` | 신규 | 헤딩 트리 추출 후 blocks. |

이 6가지가 같은 `parsed_documents.id`를 가지면 그 뒤로는 corpus layer가 출처를 가리지 않는다.

기존 코드의 `source-first`/`html-single` literal은 v0.1.5 migration 시 `source_repo`/`html_single`로 일괄 변환. enum naming convention(snake_case)에 맞춘다.

---

## `document_sources`

### 의미

"이 문서는 원래 어디서 왔는가"를 답하는 테이블이다. 원본 1개당 1 row. 같은 원본의 다른 버전·다른 언어는 별도 source가 아니라 별도 `document_versions` 또는 별도 source(언어가 다르면)로 처리한다.

### 컬럼

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| `id` | uuid | no | 원본 식별자. |
| `tenant_id` | uuid | yes | 멀티 테넌트 scope. 공식문서는 `public` 테넌트. |
| `workspace_id` | uuid | yes | 워크스페이스 scope. 공식문서는 `core`. |
| `repository_id` | uuid | yes | 라이브러리 그룹(사용자 라이브러리·운영지식·공식문서·course). |
| `owner_user_id` | text | yes | 업로드한 사용자. 공식문서는 NULL. |
| `visibility` | text | no | `private_user`, `workspace_shared`, `global_shared`. |
| `source_kind` | text | no | 위 표의 6종 (`html_single`, `source_repo`, `pptx_ocr`, `pdf_upload`, `pptx_upload`, `markdown_upload`/`txt_upload`). |
| `source_uri` | text | no | 원본 URI 또는 URL. 사용자 업로드는 storage URI. |
| `source_path` | text | yes | 로컬 경로(있을 때만). |
| `filename` | text | no | 표시·다운로드용 파일명. |
| `mime_type` | text | yes | parser dispatch에 사용. |
| `sha256` | text | no | 원본 무결성·중복 제거. |
| `storage_key` | text | no | object storage 포인터. |
| `byte_size` | bigint | no | 원본 크기. |
| `source_collection` | text | no | 코드 literal에 맞춘 2종: `core` (공식·합성), `uploaded` (사용자/PPT). |
| `source_version` | text | yes | 제품/문서 버전. 예: `4.20`. 공식문서 필수. |
| `locale` | text | yes | `ko`, `en` 등. |
| `access_policy` | jsonb | no | 접근 정책 확장 (아래 shape 참고). |
| `metadata` | jsonb | no | 출처 종류별 확장 (아래 shape 참고). |
| `created_by` | text | yes | import 액터(스크립트명/사용자). |
| `created_at` | timestamptz | no | 감사. |

### `access_policy` jsonb 허용 키

```json
{
  "access_groups": ["public"],
  "redaction_state": "not_required",
  "citation_eligible": true,
  "publication_state": "published"
}
```

이 4개 외 키는 import 단계에서 reject. 검색·답변·시민용 노출 가능 여부 판단에 직접 쓰는 값이라 컬럼화 후보지만, 정책 진화 가능성 때문에 jsonb로 유지하되 shape을 못 박는다.

### `metadata` jsonb 허용 키 (source_kind별)

공식 JSON (`source_kind = official_jsonl`):

```json
{
  "manifest_id": "ocp_ko_4_20",
  "book_slug": "advanced_networking",
  "upstream_title": "고급 네트워킹",
  "translation_status": "approved_ko",
  "translation_source_fingerprint": "c2222f7..."
}
```

PPT (`source_kind = pptx_ocr` / `pptx_upload`):

```json
{
  "deck_id": "course_pbs/intro_pbs",
  "slide_count": 28,
  "template_family": "playbook_studio_v1",
  "ocr_model": "tesseract-5",
  "ocr_language": "kor+eng"
}
```

PDF (`source_kind = pdf_upload`):

```json
{
  "parser_backend": "pymupdf",
  "page_count": 142,
  "uploaded_by_ip": "redacted"
}
```

위에 없는 키는 import에서 거부 또는 무시. parser별로 새 키가 필요해지면 본 문서에 추가하고 다음 import 라운드에 반영한다.

### 무엇을 컬럼으로, 무엇을 jsonb로?

`source_uri`, `sha256`, `source_collection`, `source_version`, `locale`, `visibility`는 컬럼 — 인덱스·필터·access scope에 직접 쓰인다.
`manifest_id`, `translation_status`, `slide_count` 같은 source-kind별 값은 jsonb — corpus 검색에는 안 쓰이고 ingestion 디버깅·재처리에만 쓰인다.

---

## `document_versions`

### 의미

같은 원본 URL이 시간이 지나면 내용이 바뀐다. 그 변경 이력을 불변 스냅샷으로 남긴다. 한 source가 여러 version을 가진다. parsing·corpus는 항상 특정 version을 가리킨다.

### 컬럼

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| `id` | uuid | no | 버전 식별자. |
| `document_source_id` | uuid | no | 부모 source. |
| `version_no` | integer | no | 1부터 증가. 같은 source 안에서 unique. |
| `source_sha256` | text | no | 이 시점의 원본 해시. |
| `storage_key` | text | no | 이 시점의 storage 포인터(불변). |
| `ingestion_run_id` | text | yes | import 실행 run id (재현용). |
| `is_current` | boolean | no | 가장 최신 버전인지. |
| `superseded_at` | timestamptz | yes | 다음 버전이 나온 시점. |
| `created_at` | timestamptz | no | 이 버전이 생긴 시점. |

### 운영 규칙

- 같은 sha256이 같은 source에 다시 들어오면 새 버전을 만들지 않는다.
- 새 sha256이면 `version_no` +1, 이전 버전의 `is_current=false`, `superseded_at`을 채운다.
- corpus는 항상 `is_current=true` 버전에서만 재생성한다. 과거 버전 corpus는 비활성으로 둔다.

---

## `parse_jobs`

### 의미

parser가 한 source-version을 처리한 한 번의 실행. 진행 상태 추적 전용. corpus truth가 아니다.

### 컬럼

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| `id` | uuid | no | 잡 식별자. |
| `document_source_id` | uuid | no | 처리한 source. |
| `document_version_id` | uuid | yes | 처리한 버전. |
| `parser_name` | text | no | `official_jsonl_parser`, `pptx_slide_graph_parser`, `pymupdf_parser`, `docling_parser` 등. |
| `parser_version` | text | no | parser 코드 버전. |
| `status` | text | no | `queued`, `running`, `completed`, `failed`, `skipped`. |
| `error_code` | text | yes | 실패 분류. |
| `error_message` | text | yes | 실패 상세. |
| `warnings_count` | integer | no | 경고 개수 (parsed_documents.warnings 길이의 합 캐시). |
| `started_at` | timestamptz | yes | 시작 시각. |
| `completed_at` | timestamptz | yes | 종료 시각. |
| `created_at` | timestamptz | no | 잡 enqueue 시각. |

---

## `parsed_documents`

### 의미

한 source-version을 parser가 처리한 결과. **parser가 본 그대로**를 담는다. 정규화·청킹·메타데이터 추출은 corpus 단계에서 한다.

한 source-version → 한 `parsed_documents` (정상 처리 시). 같은 버전을 다른 parser로 재처리하면 새 row.

### 컬럼

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| `id` | uuid | no | 식별자. |
| `document_source_id` | uuid | no | source. |
| `document_version_id` | uuid | yes | version. |
| `parse_job_id` | uuid | yes | 생성한 job. |
| `parser_name` | text | no | 사용된 parser. |
| `parser_version` | text | no | parser 버전. |
| `title` | text | yes | parser가 감지한 문서 제목. |
| `raw_text` | text | yes | 원본의 충실한 텍스트 렌더. JSON 원본은 인덱싱·디버그용. |
| `raw_payload` | jsonb | yes | 원본이 JSON일 때 그 원본 객체 자체. PPT/PDF는 NULL. |
| `outline` | jsonb | no | parser가 추출한 목차(아래 shape). |
| `warnings` | jsonb | no | parser 경고 배열. |
| `metadata` | jsonb | no | parser-specific 확장(아래 shape). |
| `created_at` | timestamptz | no | 감사. |

### `outline` jsonb shape

parser가 감지한 헤딩 트리. corpus 단계에서 section_path를 만들 때 입력으로 쓴다.

```json
[
  {"level": 1, "title": "고급 네트워킹", "anchor": "advanced-networking"},
  {"level": 2, "title": "끝점에 대한 연결 확인", "anchor": "verifying-connectivity-endpoint"},
  {"level": 3, "title": "절차", "anchor": "procedure-verifying-connectivity"}
]
```

PPT의 경우 `level`은 deck/section/slide로 매핑.

```json
[
  {"level": 1, "title": "Intro Playbook Studio", "anchor": "deck:intro_pbs"},
  {"level": 2, "title": "PV와 PVC 개념", "anchor": "slide:5"}
]
```

### `warnings` jsonb shape

```json
[
  {"code": "missing_anchor", "message": "section without anchor", "location": "slide:5"},
  {"code": "ocr_low_confidence", "message": "ocr confidence 0.41", "location": "asset:abc123"}
]
```

### `metadata` jsonb 허용 키

```json
{
  "ocr_required": true,
  "page_count": 32,
  "slide_count": 28,
  "language_detected": "ko",
  "parser_backend_options": {"ocr_lang": "kor+eng"}
}
```

### 왜 `raw_text`와 `raw_payload`를 같이 두는가

- JSON 공식문서: `raw_payload`는 원본 JSON 객체, `raw_text`는 그 JSON을 사람이 읽을 텍스트로 렌더한 것. 둘 다 corpus 단계에서 안 쓰이지만 재청킹 시 입력이 된다.
- PPT/PDF: `raw_payload=NULL`, `raw_text`만 슬라이드/페이지 텍스트로 채움.
- 이 분리는 "원본이 JSON이라서 corpus도 JSON 키를 봐야 한다"는 잘못된 결합을 막는다.

---

## `document_blocks`

### 의미

parser가 문서를 구조 단위로 쪼갠 결과. **chunking 이전 단계**의 원자 단위다. 한 parsed_document가 보통 수십~수천 개 block을 가진다.

block은 corpus chunk와 1:N이 아니다 — 한 chunk가 여러 block을 묶을 수도, 한 block이 여러 chunk로 쪼개질 수도 있다. block은 "원본의 구조 그대로", chunk는 "검색·답변에 좋은 단위로 재구성".

### 컬럼

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| `id` | uuid | no | 블록 식별자. |
| `parsed_document_id` | uuid | no | 부모. |
| `ordinal` | integer | no | 문서 내 순서. |
| `block_type` | text | no | 아래 enum. |
| `block_role` | text | yes | 아래 enum. |
| `heading_level` | integer | yes | 헤딩일 때 레벨. |
| `page_number` | integer | yes | PDF 페이지 번호. |
| `slide_number` | integer | yes | PPT 슬라이드 번호. |
| `text` | text | yes | 블록의 원본 텍스트. |
| `markdown` | text | yes | 블록의 markdown 렌더(인라인 마크업 없음). |
| `code_language` | text | yes | code block일 때 언어 (`shell`, `yaml`, `text`, `json` 등). |
| `table_data` | jsonb | yes | table block일 때 구조화된 표(rows, header). |
| `section_path` | jsonb | no | parser가 본 섹션 경로 배열. |
| `section_number` | text | yes | 섹션 번호 (예: "1.2.3"). |
| `heading_title` | text | yes | 가장 가까운 상위 헤딩. |
| `source_anchor` | text | yes | 원본의 anchor/id. |
| `source_json_path` | text | yes | 원본이 JSON일 때 JSON Pointer (`$.books[0].chapters[2].steps[4]`). |
| `source_location` | jsonb | no | 위치 provenance(아래 shape). |
| `ocr_text` | text | yes | 이미지 블록의 OCR 결과. |
| `ocr_confidence` | numeric | yes | OCR 신뢰도 (0.0~1.0). |
| `image_description` | text | yes | 이미지 블록의 vision 설명. |
| `asset_id` | uuid | yes | 이미지·표 블록일 때 `document_assets.id`. |
| `metadata` | jsonb | no | parser-specific 확장. |

### `block_type` enum

```text
heading           헤딩
paragraph         일반 문단
list_item         리스트 항목
code              코드(쉘 명령·yaml·json 등)
code_output       명령 실행 결과 예시
table             표
note              인포 박스(info/note)
warning           경고 박스
admonition        기타 인포 박스
image             이미지
figure            도표
quote             인용
slide_zone        PPT 슬라이드 내 텍스트 zone
slide_attachment  PPT 슬라이드 내 이미지/도표 attachment
```

### `block_role` enum

```text
concept           개념 설명
procedure         절차 단계
command           실행 명령
verification      확인·검증
prerequisite      사전 조건
example           예시
output            출력 예시
reference         참고 자료
navigation        목차·링크 모음
noise             버려도 되는 footer/header
```

`block_role`은 nullable. parser가 자신 있을 때만 채우고, 모를 때 비워둔다. corpus 단계에서 NLP/휴리스틱으로 보완.

### `source_location` jsonb shape

```json
{
  "page": 17,
  "slide": null,
  "bbox": {"x": 0.1, "y": 0.2, "w": 0.8, "h": 0.05},
  "upstream_id": "sec-create-install-config",
  "zone_id": "zone-3"
}
```

존재하는 키만 채우면 됨. 검색 ranking에는 안 쓰이고, 뷰어 점프·재파싱·디버그에 쓰임.

### `metadata` jsonb 허용 키

```json
{
  "parser_hint": {"detected_language": "ko"},
  "raw_html_class": "procedure-step",
  "slide_zone_type": "title",
  "slide_zone_role": "step",
  "ppt_layout_hint": "has_numbered_steps"
}
```

PPT의 slide_zone 정보(zone_type, role, layout_hint)는 이 metadata에 담는다 — corpus 단계에서 chunk segment_type을 결정하는 입력으로 쓴다.

### 원본별 block 매핑 예시

**JSON 공식문서 chunk 한 개:**

원본:
```json
{
  "chunk_id": "...",
  "section": "끝점에 대한 연결 확인",
  "text": "고급 네트워킹\n1장. 끝점에 대한 연결 확인\n\nCNO(Cluster Network Operator)는 ..."
}
```

→ 하나의 chunk가 보통 여러 block으로 펼쳐진다 (parser가 `text` 안의 `[CODE]` 마크업 등을 분해). 예:

| ordinal | block_type | block_role | text/code |
| --- | --- | --- | --- |
| 0 | heading | — | "1장. 끝점에 대한 연결 확인" |
| 1 | paragraph | concept | "CNO는 클러스터 내 리소스 간에..." |
| 2 | code | command | `oc get pods -n openshift-network-diagnostics` |
| 3 | code_output | output | "NAME ... STATUS Running" |
| 4 | paragraph | verification | "Running이 표시되면 정상입니다." |

**PPT 슬라이드 한 개:**

원본 `slide_graph` slide:
```json
{
  "slide_no": 5,
  "design_title": "PVC 확인 절차",
  "zones": [
    {"text": "PVC 확인 절차", "role": "title", "order_hint": 0},
    {"text": "1. oc get pvc 로 상태 확인", "role": "step", "order_hint": 1},
    {"text": "2. oc describe pvc 로 상세 확인", "role": "step", "order_hint": 2}
  ],
  "attachments": [{"kind": "slide_image", "ocr_text": "STATUS Bound", "attachment_id": "..."}]
}
```

→ blocks:

| ordinal | block_type | block_role | text |
| --- | --- | --- | --- |
| 0 | heading | — | "PVC 확인 절차" |
| 1 | slide_zone | procedure | "1. oc get pvc 로 상태 확인" |
| 2 | slide_zone | procedure | "2. oc describe pvc 로 상세 확인" |
| 3 | slide_attachment | example | (image) OCR: "STATUS Bound" |

→ corpus chunk 1개로 묶이지만, block_role이 `procedure`/`example`로 나뉘어 있어 corpus chunk segment 생성 시 typed segment로 매핑된다.

---

## `document_assets`

### 의미

추출된 이미지·도표·표 이미지·첨부 파일. 본문은 `document_blocks.text`에 있지만, 이미지 자체와 그 OCR/캡션/AI 설명은 별도 row로 둔다. 동일 이미지가 여러 block에서 참조될 수 있다.

### 컬럼

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| `id` | uuid | no | 자산 식별자. |
| `document_source_id` | uuid | no | source. |
| `parsed_document_id` | uuid | yes | parsed 문서. |
| `block_id` | uuid | yes | 1차 참조 블록. |
| `asset_type` | text | no | `image`, `figure`, `table_image`, `slide_image`, `attachment`. |
| `mime_type` | text | yes | MIME. |
| `storage_key` | text | no | asset storage 포인터. |
| `sha256` | text | no | 자산 해시. |
| `width` | integer | yes | 이미지 width. |
| `height` | integer | yes | 이미지 height. |
| `page_number` | integer | yes | PDF 페이지. |
| `slide_number` | integer | yes | PPT 슬라이드. |
| `bbox` | jsonb | yes | 레이아웃 박스. |
| `caption_text` | text | yes | 추출된 캡션. |
| `ocr_text` | text | yes | OCR 원문. |
| `ocr_confidence` | numeric | yes | OCR 신뢰도. |
| `image_description` | text | yes | 모델 중립 vision 설명. |
| `description_model` | text | yes | 설명 생성 모델 (`qwen-vl-7b`, `gpt-4o-vision`, ...). |
| `description_status` | text | no | `missing`, `generated`, `failed`, `skipped`. |
| `metadata` | jsonb | no | 도구별 확장. |
| `created_at` | timestamptz | no | 감사. |

### 레거시 이름 정리

현재 `qwen_description` / `qwen_model` 컬럼이 있다. 이 두 컬럼은 v0.1.5 마이그레이션에서 `image_description` / `description_model` 로 rename한다. 이름이 특정 모델에 묶이면 다음 vision 모델로 갈아탈 때 schema가 흔들린다.

### `metadata` jsonb 허용 키

```json
{
  "extracted_by": "pymupdf-image-extract-v1",
  "exif_stripped": true,
  "duplicate_of": null,
  "alt_text_source": "official_html_alt"
}
```

---

## Parsing layer 운영 규칙

1. **Parsing 테이블은 idempotent하다.** 같은 source-version을 같은 parser로 재처리하면 기존 `parsed_documents` row와 그 자식들이 트랜잭션 안에서 교체된다.
2. **Parsing 테이블 위에서 검색·답변을 하지 않는다.** corpus가 비어 있어도 parsing은 채워질 수 있다. 그 반대도 같다 — corpus를 만들지 못한 source는 `parsed_documents`까지만 도달.
3. **Parsing에 있는 모든 jsonb는 본 문서가 허용한 키만 받는다.** 새 키가 필요하면 본 문서를 먼저 갱신.
4. **block_type, block_role, asset_type, source_kind, status는 enum 후보지만 v0.1.5 마이그레이션에서는 text + CHECK constraint로 시작.** 진짜 enum 타입은 값이 안정되면 v0.1.6에서.
5. **검색 intent/search signal은 parsing layer에서 만들지 않는다.** parser는 원문 구조, 코드 블록, 표, 이미지/OCR, anchor, source provenance만 보존한다. `intent_labels`, `answer_shapes`, `best_for_questions`, `cluster_phase`, `execution_target` 같은 RAG 라우팅 신호는 corpus enrichment / Intent Agent 계약에서 생성한다.

## Parsing → Corpus 매핑은 어디에 있나

`spec/v0.1.4/db-corpus-schema.md`에 다음 매핑이 정의된다:

- `parsed_documents` → `corpus_documents` (1:1, normalize/enrich)
- `document_blocks` → `corpus_chunks` + `corpus_chunk_segments` (N:M, 청킹·세그멘트화)
- `document_assets` → `corpus_chunks.asset_ids` 참조 (asset 자체는 parsing에 남고, chunk가 참조)
- `document_blocks` 중 `block_type=code` & `block_role=command` → `corpus_chunk_commands` (커맨드 추출)
- `document_blocks`의 원문 구조 + `corpus_chunks` enrichment → Qdrant `source` / `classification` / `chunk` / `search_signals` / `text` payload projection. Parsing table이 Qdrant payload를 직접 만들지 않는다.
