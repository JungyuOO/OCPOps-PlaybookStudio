# 260517 Official Corpus Text Layer Correction

## 목적

v0.1.4 official corpus 작업 중 J 검수에서 확인된 텍스트 계층 적용 오류를 정리하고, 어떤 방식으로 수정했는지 기록한다.

이번 문서는 새 청킹 전략을 추가 제안하는 문서가 아니라, 이미 협의된 v0.1.4 계약을 실제 구현과 Qdrant payload에 맞게 되돌린 correction note다.

## 기준 계약

v0.1.4의 텍스트 계층은 다음 역할로 분리한다.

| 계층 | 역할 |
| --- | --- |
| `raw_text` | 원본 보존. 지저분해도 보존한다. |
| `markdown` / `text` | 사람과 챗봇 답변 화면에 보여줄 표시용 본문. 코드블록, 개행, 표 표현을 유지한다. |
| `normalized_text` | BM25/keyword 검색용 flat text. 불필요한 기호와 마크업을 제거한다. |
| `embedding_text` | vector embedding 입력용 flat text. 마크업, 목차, URL, base64 출력 예시 등 검색 노이즈를 제거하되 명령어의 의미 기호는 유지한다. |

## 확인된 문제

### 1. 표시용 text와 embedding_text가 같은 값으로 들어감

이전 구현에서는 `embedding_chunks.jsonl`의 `text`와 Qdrant `payload.text`가 `embedding_text`와 같은 값으로 저장됐다.

문제:

- 챗봇 또는 viewer가 `payload.text`를 표시용 본문처럼 읽을 때 flat한 임베딩 텍스트가 노출될 수 있다.
- 원문 코드블록, 개행, 백틱, 표 표현이 답변 근거 표시에서 사라진다.
- 검수자가 `text`, `normalized_text`, `embedding_text`가 모두 같아 보이는 케이스를 확인할 수 있다.

원인:

- Qdrant 기존 retriever 호환을 맞추는 과정에서 `payload.text`를 vector 입력 alias처럼 좁게 해석했다.
- v0.1.4 계약상 `text`는 표시용이고, `text_fields.embedding_text`가 vector 입력이어야 한다.

### 2. base64 출력 예시가 normalized_text / embedding_text에 포함됨

J가 확인한 예:

```text
Tk9ERUlQX0hJTlQ9MTkyLjAuMCxxxx==
```

이 값은 source `chunks.jsonl`의 코드블록 출력 예시에 있던 값이다.
추가 재검토 과정에서는 padding이 없는 `Tk9ERUlQX0hJTlQ9MTkyLjAuMC` 형태도 같은 계열의 encoded sample output으로 확인했다.

문제:

- `text` 또는 `markdown`에는 원문 표시용으로 남아도 된다.
- 하지만 `normalized_text`와 `embedding_text`에 들어가면 의미 검색에 도움이 되지 않는 고유 문자열 노이즈가 된다.
- 특히 vector 검색에서는 질문과 무관한 encoded sample output이 벡터 입력에 섞여 품질을 낮출 수 있다.

원인:

- 코드블록 본문을 embedding text로 평탄화하면서 명령어와 출력 예시를 충분히 구분하지 못했다.
- base64-like token을 embedding/normalized 계층에서 제거하는 필터가 없었다.

### 3. 청크 사이즈 오해 가능성

이번 작업은 새 chunk size를 지정해서 다시 rechunk한 작업이 아니다.

정확한 상태:

- 원본 source는 기존 `chunks.jsonl`이다.
- 기존 `chunk_id` 기준으로 text layer projection을 생성했다.
- `embedding_chunks.jsonl` row 수가 줄어든 이유는 새 chunk size 때문이 아니라 empty / exact duplicate / contained overlap projection 제외 때문이다.

생성 결과:

| 항목 | 값 |
| --- | ---: |
| source `chunks.jsonl` rows | 27,907 |
| `text_layers.jsonl` rows | 27,907 |
| `embedding_chunks.jsonl` rows | 25,882 |
| skipped empty embedding | 118 |
| skipped exact duplicate | 484 |
| skipped contained overlap | 1,423 |

## 수정 내용

### 1. embedding projection의 text를 표시용 markdown으로 변경

파일:

- `src/play_book_studio/ingestion/official_gold_import.py`

변경:

- `embedding_chunks.jsonl.text`를 `embedding_text`가 아니라 `_normalized_chunk_text(row)` 결과인 표시용 markdown으로 저장한다.
- `embedding_text`는 vector 입력 전용 flat text로 유지한다.
- `normalized_text`는 BM25/keyword용 flat text로 유지한다.

정상 예:

```json
{
  "text": "```shell\n$ oc create configmap ... \\\n    -n openshift-config\n```",
  "normalized_text": "oc create configmap keycloak oidc ca from file ca bundle crt ...",
  "embedding_text": "$ oc create configmap keycloak-oidc-ca --from-file=ca-bundle.crt ... -n openshift-config"
}
```

### 2. Qdrant payload의 표시용 본문과 embedding 본문 분리

파일:

- `src/play_book_studio/db/qdrant_indexer.py`

변경:

- `payload.text`는 `markdown` 우선으로 채운다.
- `payload.markdown`도 표시용 markdown을 유지한다.
- `payload.text_fields.embedding_text`는 `document_chunks.embedding_text` 기준으로 채운다.
- `payload.text_fields.normalized_text`는 BM25/keyword용 값을 유지한다.

정상 계약:

```text
payload.text                         = 표시/답변용 markdown
payload.markdown                     = 표시/답변용 markdown
payload.text_fields.normalized_text  = BM25/keyword용 flat text
payload.text_fields.embedding_text   = vector input용 flat text
```

### 3. base64-like 출력 예시를 embedding/normalized 계층에서 제거

파일:

- `src/play_book_studio/ingestion/official_gold_import.py`

변경:

- `Tk9ERUlQX0hJTlQ9MTkyLjAuMCxxxx==`처럼 padding이 붙은 base64-like token과 `Tk9ERUlQX0hJTlQ9MTkyLjAuMC`처럼 padding이 없는 base64-like token을 embedding text 생성 단계에서 제거한다.
- `normalized_text`는 `embedding_text` 기반으로 생성되므로 동일하게 제거된다.
- `text`, `markdown`, `raw_text`에는 원문 표시/보존 목적상 남긴다.

검증한 chunk:

```text
98841828-a3c1-56f9-bdaf-eeaf9238c2db
```

검증 결과:

```text
text_has_Tk9        : True
normalized_has_Tk9 : False
embedding_has_Tk9  : False
```

### 4. 품질 게이트 수정

파일:

- `src/play_book_studio/ingestion/official_embedding_qdrant.py`

변경:

- 기존 `payload.text == text_fields.embedding_text` 검사는 제거했다.
- 대신 다음을 검사한다.
  - `payload.text`가 비어 있지 않은지
  - `text_fields.embedding_text`가 실제 candidate embedding input과 일치하는지
  - `raw_text`가 Qdrant payload에 유출되지 않는지
  - `embedding_text`에 개행, 내부 marker, fenced code, URL, percent encoding, Arabic contamination, base64-like token이 없는지

## 검증 결과

### 1. local artifact 재생성

명령:

```powershell
.\.venv\Scripts\python.exe -m play_book_studio.cli official-gold-import `
  --dry-run `
  --embedding-chunks-path corpus\sources\official\imported-gold\gold_corpus_ko\embeddings\embedding_chunks.jsonl `
  --text-layers-path corpus\sources\official\imported-gold\gold_corpus_ko\text-layers\text_layers.jsonl
```

결과:

```json
{
  "chunk_count": 27907,
  "embedding_chunks": {
    "input_chunk_count": 27907,
    "embedding_chunk_count": 25882,
    "skipped_empty_embedding_count": 118,
    "skipped_exact_duplicate_embedding_count": 484,
    "skipped_contained_overlap_embedding_count": 1423
  },
  "text_layers": {
    "input_chunk_count": 27907,
    "text_layer_row_count": 27907,
    "embedding_text_present_count": 27789
  }
}
```

### 2. Qdrant dry-run 품질 게이트

명령:

```powershell
.\.venv\Scripts\python.exe -m play_book_studio.cli official-embedding-qdrant-upsert `
  --dry-run `
  --collection openshift_docs
```

결과:

```json
{
  "collection": "openshift_docs",
  "qdrant_url": "http://127.0.0.1:6335",
  "candidate_count": 25882,
  "target_embedding_point_count": 25882,
  "skipped_source_point_count": 2025,
  "dry_run": true,
  "quality": {
    "empty_text": 0,
    "internal_marker_or_fence": 0,
    "html_anchor_or_docs_url": 0,
    "percent_encoded": 0,
    "broken_dot_placeholder": 0,
    "html_entity_angle": 0,
    "tab": 0,
    "arabic": 0,
    "base64_like": 0,
    "embedding_not_flat": 0,
    "quote": 0,
    "raw_text_payload_keys": 0,
    "payload_text_empty": 0,
    "payload_embedding_text_mismatch": 0,
    "normalized_not_flat": 0
  }
}
```

### 3. DB/Qdrant 반영

처음 실행한 명령은 `.env`의 Docker 내부 호스트명 `postgres`를 사용해 로컬 PowerShell에서 실패했다.

실패 원인:

```text
psycopg.OperationalError: failed to resolve host 'postgres'
```

로컬 PowerShell에서는 host를 `127.0.0.1`로 지정해 재실행했다.

명령:

```powershell
.\.venv\Scripts\python.exe -m play_book_studio.cli official-embedding-qdrant-upsert `
  --collection openshift_docs `
  --delete-skipped `
  --sync-db `
  --database-url postgresql://admin:admin123@127.0.0.1:5432/playbookstudio
```

결과:

```json
{
  "collection": "openshift_docs",
  "qdrant_url": "http://127.0.0.1:6335",
  "candidate_count": 25882,
  "target_embedding_point_count": 25882,
  "skipped_source_point_count": 2025,
  "delete_skipped": true,
  "dry_run": false,
  "upserted_count": 25882,
  "deleted_skipped_count": 2025,
  "db_sync": {
    "updated_embedding_text_count": 25882,
    "suppressed_embedding_text_count": 2025
  },
  "qdrant_index_entries": {
    "recorded_index_entry_count": 25882,
    "deleted_skipped_index_entry_count": 2025
  }
}
```

### 4. Qdrant official point count 확인

명령:

```powershell
@'
import json, urllib.request

body = {
    "exact": True,
    "filter": {
        "must": [
            {"key": "source.corpus_scope", "match": {"value": "official_docs"}}
        ]
    },
}

req = urllib.request.Request(
    "http://127.0.0.1:6335/collections/openshift_docs/points/count",
    data=json.dumps(body).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

print(json.dumps(json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8")), ensure_ascii=False, indent=2))
'@ | .\.venv\Scripts\python.exe -
```

결과:

```json
{
  "result": {
    "count": 25882
  },
  "status": "ok"
}
```

### 5. DB text layer / index 상태 확인

명령:

```powershell
@'
import json, psycopg

conn = psycopg.connect("postgresql://admin:admin123@127.0.0.1:5432/playbookstudio")
queries = {
    "official_chunks": "select count(*) from document_chunks where source_scope = 'official_docs'",
    "official_embedding_nonempty": "select count(*) from document_chunks where source_scope = 'official_docs' and coalesce(embedding_text, '') <> ''",
    "official_text_layers": "select count(*) from document_chunks where source_scope = 'official_docs' and metadata ? 'text_layers'",
    "official_index_entries": "select count(*) from qdrant_index_entries q join document_chunks c on c.id = q.chunk_id where c.source_scope = 'official_docs' and q.collection = 'openshift_docs'",
    "embedding_has_tk9": "select count(*) from document_chunks where source_scope = 'official_docs' and coalesce(embedding_text, '') like '%Tk9ERUlQ%'",
    "normalized_has_tk9": "select count(*) from document_chunks where source_scope = 'official_docs' and coalesce(metadata->>'normalized_text', '') like '%Tk9ERUlQ%'",
    "layer_embedding_has_tk9": "select count(*) from document_chunks where source_scope = 'official_docs' and coalesce(metadata->'text_layers'->>'embedding_text', '') like '%Tk9ERUlQ%'",
    "layer_normalized_has_tk9": "select count(*) from document_chunks where source_scope = 'official_docs' and coalesce(metadata->'text_layers'->>'normalized_text', '') like '%Tk9ERUlQ%'",
}
result = {}
with conn.cursor() as cur:
    for key, sql in queries.items():
        cur.execute(sql)
        result[key] = cur.fetchone()[0]
print(json.dumps(result, ensure_ascii=False, indent=2))
'@ | .\.venv\Scripts\python.exe -
```

결과:

```json
{
  "official_chunks": 27907,
  "official_embedding_nonempty": 25882,
  "official_text_layers": 27907,
  "official_index_entries": 25882,
  "embedding_has_tk9": 0,
  "normalized_has_tk9": 0,
  "layer_embedding_has_tk9": 0,
  "layer_normalized_has_tk9": 0
}
```

### 6. J가 지적한 base64 sample chunk 확인

확인 대상:

```text
98841828-a3c1-56f9-bdaf-eeaf9238c2db
```

명령:

```powershell
$ids = @(
  "98841828-a3c1-56f9-bdaf-eeaf9238c2db"
)

$body = @{
  ids = $ids
  with_payload = $true
  with_vector = $false
} | ConvertTo-Json -Depth 20

$r = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:6335/collections/openshift_docs/points" `
  -ContentType "application/json" `
  -Body $body

$r.result | ForEach-Object {
  $p = $_.payload
  $f = $p.text_fields

  "chunk_id        : $($p.chunk_id)"
  "book_slug       : $(if ($p.book_slug) { $p.book_slug } else { $p.classification.book_slug })"
  "section_path    : $($p.section_path -join ' > ')"
  "text:"
  $p.text
  "normalized_text:"
  $f.normalized_text
  "embedding_text:"
  $f.embedding_text
  "text_has_Tk9        : $($p.text -like '*Tk9ERUlQ*')"
  "normalized_has_Tk9 : $($f.normalized_text -like '*Tk9ERUlQ*')"
  "embedding_has_Tk9  : $($f.embedding_text -like '*Tk9ERUlQ*')"
}
```

결과:

```text
chunk_id        : 98841828-a3c1-56f9-bdaf-eeaf9238c2db
book_slug       : support
section_path    : 7장. 문제 해결 > 네트워크 문제 해결 > 네트워크 인터페이스 선택 방법 > 선택 사항: 기본 노드 IP 선택 논리를 덮어 쓰기

text:
출력 예
```shell
Tk9ERUlQX0hJTlQ9MTkyLjAuMCxxxx==
```

클러스터를 배포하기 전에 `master` 및 `worker` 역할에 대한 머신 구성 매니페스트를 생성하여 힌트를 활성화합니다.

normalized_text:
클러스터를 배포하기 전에 master 및 worker 역할에 대한 머신 구성 매니페스트를 생성하여 힌트를 활성화합니다

embedding_text:
클러스터를 배포하기 전에 master 및 worker 역할에 대한 머신 구성 매니페스트를 생성하여 힌트를 활성화합니다

text_has_Tk9        : True
normalized_has_Tk9 : False
embedding_has_Tk9  : False
```

판단:

- `text`에는 코드블록 출력 예시가 남아 있으므로 `True`가 정상이다.
- `normalized_text`와 `embedding_text`에서는 제거됐으므로 `False`가 정상이다.
- 따라서 `embedding_chunks.jsonl` 전체 줄을 단순 `rg Tk9ERUlQ`로 검색하면 표시용 `text` 때문에 hit가 나올 수 있다. 검수는 JSON field 단위로 `normalized_text` / `embedding_text`를 따로 봐야 한다.

field 단위 로컬 파일 scan:

```powershell
@'
import json
from pathlib import Path

p = Path(r"corpus\sources\official\imported-gold\gold_corpus_ko\embeddings\embedding_chunks.jsonl")
counts = {
    "line_contains_tk9": 0,
    "text_contains_tk9": 0,
    "normalized_contains_tk9": 0,
    "embedding_contains_tk9": 0,
}
for line in p.open(encoding="utf-8"):
    if "Tk9ERUlQ" in line:
        counts["line_contains_tk9"] += 1
    row = json.loads(line)
    if "Tk9ERUlQ" in str(row.get("text", "")):
        counts["text_contains_tk9"] += 1
    if "Tk9ERUlQ" in str(row.get("normalized_text", "")):
        counts["normalized_contains_tk9"] += 1
    if "Tk9ERUlQ" in str(row.get("embedding_text", "")):
        counts["embedding_contains_tk9"] += 1
print(json.dumps(counts, ensure_ascii=False, indent=2))
'@ | .\.venv\Scripts\python.exe -
```

결과:

```json
{
  "line_contains_tk9": 6,
  "text_contains_tk9": 6,
  "normalized_contains_tk9": 0,
  "embedding_contains_tk9": 0
}
```

### 7. Qdrant 전체 official docs payload scan

명령:

```powershell
@'
import json, re, urllib.request

body = {
    "limit": 2000,
    "with_payload": True,
    "with_vector": False,
    "filter": {
        "must": [
            {"key": "source.corpus_scope", "match": {"value": "official_docs"}}
        ]
    },
}

url = "http://127.0.0.1:6335/collections/openshift_docs/points/scroll"
base64_re = re.compile(r"(?<![A-Za-z0-9+/])(?:[A-Za-z0-9+/]{20,}={0,2})(?![A-Za-z0-9+/])")

def is_likely_base64_token(value):
    token = str(value or "").rstrip("=")
    return (
        len(token) >= 20
        and any(char.isupper() for char in token)
        and any(char.islower() for char in token)
        and any(char.isdigit() for char in token)
    )

counts = {
    "checked": 0,
    "embedding_newline": 0,
    "embedding_marker": 0,
    "embedding_base64_like": 0,
    "normalized_newline": 0,
    "raw_text_leak": 0,
    "empty_payload_text": 0,
    "payload_embedding_mismatch": 0,
}

offset = None
while True:
    if offset is not None:
        body["offset"] = offset
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    data = json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))["result"]
    for point in data.get("points", []):
        payload = point.get("payload") or {}
        fields = payload.get("text_fields") or {}
        embedding_text = str(fields.get("embedding_text") or "")
        normalized_text = str(fields.get("normalized_text") or "")
        counts["checked"] += 1
        if not str(payload.get("text") or "").strip():
            counts["empty_payload_text"] += 1
        if "\n" in embedding_text or "\t" in embedding_text or "\r" in embedding_text:
            counts["embedding_newline"] += 1
        if any(marker in embedding_text for marker in ("[CODE", "[/CODE]", "[TABLE", "[/TABLE]", "```")):
            counts["embedding_marker"] += 1
        if any(is_likely_base64_token(match.group(0)) for match in base64_re.finditer(embedding_text)):
            counts["embedding_base64_like"] += 1
        if "\n" in normalized_text or "\t" in normalized_text or "\r" in normalized_text:
            counts["normalized_newline"] += 1
        if "raw_text" in json.dumps(payload, ensure_ascii=False):
            counts["raw_text_leak"] += 1
    offset = data.get("next_page_offset")
    if not offset:
        break

print(json.dumps(counts, ensure_ascii=False, indent=2))
'@ | .\.venv\Scripts\python.exe -
```

결과:

```json
{
  "checked": 25882,
  "embedding_newline": 0,
  "embedding_marker": 0,
  "embedding_base64_like": 0,
  "normalized_newline": 0,
  "raw_text_leak": 0,
  "empty_payload_text": 0,
  "payload_embedding_mismatch": 0
}
```

판단:

- J가 지적한 base64-like output이 `embedding_text`에 남는 문제는 padding이 있는 형태와 없는 형태 모두 전체 official Qdrant payload 기준 0건으로 확인했다.
- `payload.text`는 표시용이므로 코드블록과 개행이 남을 수 있다. 품질 검사는 `text_fields.embedding_text` 기준으로 수행했다.

### 8. 코드/문서 검증

명령:

```powershell
.\.venv\Scripts\python.exe -m compileall -q `
  src\play_book_studio\ingestion\official_gold_import.py `
  src\play_book_studio\ingestion\official_embedding_qdrant.py `
  src\play_book_studio\db\qdrant_indexer.py
```

결과:

```text
통과
```

명령:

```powershell
git diff --check
```

결과:

```text
통과
```

관련 테스트 함수 직접 호출:

```powershell
@'
import tests.test_official_gold_import as t1
import tests.test_qdrant_indexer as t2
import tests.test_bm25_postgres as t3

for fn in [
    t1.test_write_official_embedding_chunks_creates_clean_embedding_projection,
    t1.test_write_official_embedding_chunks_removes_encoded_output_only_from_search_layers,
    t1.test_write_official_text_layers_exports_four_layer_contract,
    t1.test_build_official_embedding_qdrant_candidates_uses_clean_text_without_raw_payload,
    t2.test_qdrant_payload_from_row_matches_vector_retriever_contract,
    t2.test_qdrant_payload_from_row_preserves_official_gold_metadata,
    t2.test_qdrant_candidate_from_row_hashes_stable_payload,
    t2.test_refresh_stale_qdrant_payloads_updates_existing_candidates,
    t3.test_bm25_index_uses_normalized_text_for_matching_but_returns_display_text,
]:
    fn()
    print(f"PASS {fn.__name__}")
'@ | .\.venv\Scripts\python.exe -
```

결과:

```text
PASS test_write_official_embedding_chunks_creates_clean_embedding_projection
PASS test_write_official_embedding_chunks_removes_encoded_output_only_from_search_layers
PASS test_write_official_text_layers_exports_four_layer_contract
PASS test_build_official_embedding_qdrant_candidates_uses_clean_text_without_raw_payload
PASS test_qdrant_payload_from_row_matches_vector_retriever_contract
PASS test_qdrant_payload_from_row_preserves_official_gold_metadata
PASS test_qdrant_candidate_from_row_hashes_stable_payload
PASS test_refresh_stale_qdrant_payloads_updates_existing_candidates
PASS test_bm25_index_uses_normalized_text_for_matching_but_returns_display_text
```

참고:

- 로컬 venv에 `pytest`가 설치되어 있지 않아 `python -m pytest ...` runner는 실행하지 못했다.
- 대신 관련 테스트 함수를 직접 호출해 현재 변경 범위의 핵심 계약을 검증했다.

## 요약 검증표

로컬 Qdrant:

```text
qdrant_url: http://127.0.0.1:6335
collection: openshift_docs
official_docs points: 25,882
```

전체 official docs point scan 결과:

| 항목 | 결과 |
| --- | ---: |
| checked official points | 25,882 |
| `embedding_text` newline/tab | 0 |
| `embedding_text` marker/fence | 0 |
| `embedding_text` base64-like token | 0 |
| `normalized_text` newline/tab | 0 |
| Qdrant `raw_text` leak | 0 |
| empty `payload.text` | 0 |
| `text_fields.embedding_text` mismatch | 0 |

샘플 확인:

```text
chunk_id: 98841828-a3c1-56f9-bdaf-eeaf9238c2db

text:
출력 예
```shell
Tk9ERUlQX0hJTlQ9MTkyLjAuMCxxxx==
```

클러스터를 배포하기 전에 `master` 및 `worker` 역할에 대한 머신 구성 매니페스트를 생성하여 힌트를 활성화합니다.

normalized_text:
클러스터를 배포하기 전에 master 및 worker 역할에 대한 머신 구성 매니페스트를 생성하여 힌트를 활성화합니다

embedding_text:
클러스터를 배포하기 전에 master 및 worker 역할에 대한 머신 구성 매니페스트를 생성하여 힌트를 활성화합니다
```

테스트:

- 현재 로컬 venv에는 `pytest`가 설치되어 있지 않아 pytest runner는 실행하지 못했다.
- 관련 테스트 함수 직접 호출 결과 통과:
  - `test_write_official_embedding_chunks_creates_clean_embedding_projection`
  - `test_write_official_embedding_chunks_removes_encoded_output_only_from_search_layers`
  - `test_write_official_text_layers_exports_four_layer_contract`
  - `test_build_official_embedding_qdrant_candidates_uses_clean_text_without_raw_payload`
  - `test_qdrant_payload_from_row_matches_vector_retriever_contract`
  - `test_qdrant_payload_from_row_preserves_official_gold_metadata`
  - `test_qdrant_candidate_from_row_hashes_stable_payload`
  - `test_refresh_stale_qdrant_payloads_updates_existing_candidates`
  - `test_bm25_index_uses_normalized_text_for_matching_but_returns_display_text`
- `python -m compileall` 통과.
- `git diff --check` 통과.

## 브랜치와 커밋

작업 브랜치:

```text
feat/corpus_embedding_text_s
```

수정 커밋:

```text
1278063 fix: separate official display and embedding text
c1d2b64 docs: record official corpus correction evidence
cb64c1d fix: tighten official embedding noise gates
```

## 참고

이번 수정은 v0.1.4 계약에 맞게 official corpus의 텍스트 계층을 바로잡은 작업이다.

이번 재점검에서 추가 확인한 부분:

- padding 없는 base64-like token 4건이 DB 검색 계층에 남아 있던 것을 추가 발견했고, 필터와 Qdrant 품질 게이트를 확장했다.
- 재생성/재적재 후 DB의 `document_chunks.embedding_text`, `metadata.text_layers.embedding_text`, `metadata.text_layers.normalized_text`에서 `Tk9ERUlQ` 계열 문자열 0건을 확인했다.
- Qdrant official docs payload 전체 scan에서도 `embedding_base64_like=0`을 확인했다.

추가 점검 후 바로 처리한 부분:

- BM25 runtime loader는 `payload.text`가 아니라 `text_fields.normalized_text` / `normalized_text`를 우선 토큰화하도록 수정했다. 표시용 `text`는 검색 hit 반환용으로 유지된다.
- docker compose seed에서 사용하는 `--refresh-qdrant-payloads` 경로는 stale payload 후보를 payload만 덮어쓰지 않고, 새 `embedding_text`로 벡터까지 다시 upsert하도록 수정했다. 기존 collection 재사용 시 stale vector가 남는 리스크를 줄이기 위한 조치다.

아직 "완료"로 과하게 말하면 안 되는 부분:

- 반복이 많은 표 chunk는 `normalized_text == embedding_text`가 될 수 있다. 이 자체는 오류가 아니지만, retrieval rank에서 낮게 보거나 metadata로 table 성격을 반영할 수 있다.
- 새 chunk size로 rechunk한 작업은 아니므로, 청크 크기 정책을 변경하려면 별도 회의와 산출물이 필요하다.
- `text`/`markdown`에는 표시용 코드블록이 남는 것이 정상이다. 임베딩 품질 검사는 `text_fields.embedding_text` 기준으로 보는 것이 맞다.
