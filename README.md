# PlayBookStudio

이 저장소는 `PlayBookStudio(PBS)`를 다른 프로젝트에 편입하기 위해 정리한 최소 기준선입니다.

원래 작업 저장소 전체를 넘긴 것이 아니라, 편입에 필요한 코드와 데이터만 남긴 상태입니다.

## 포함한 것

- `presentation-ui/`
- `src/`
- `data/wiki_runtime_books`
- `data/wiki_assets`
- `data/wiki_relations`
- `data/gold_candidate_books`
- `data/gold_manualbook_ko`
- `data/silver_ko`
- `data/gold_corpus_ko`
- `manifests/`
- `schemas/`
- `tests/`
- 루트 실행 파일과 설정 파일

## 뺀 것

- 다른 root markdown 문서
- scripts
- pipelines
- execution harness 결과물
- build logs
- quarantine 데이터
- 실험/디버그 산출물
- 로컬 launcher 잔재
- 편입에 직접 필요 없는 보조 자료

## 유지하는 경로

- `/`
- `/studio`
- `/workspace`
- `/llmwikibook`
- `/playbook-library`
- `/partner/*`

기본 원칙은 아래와 같습니다.

- PBS 경로는 유지
- shared landing만 공유
- partner 기능은 `/partner/*` 아래에서 분리

## 데이터

이번 편입 브랜치에는 아래 3개 데이터가 포함되어 있습니다.

- `data/gold_manualbook_ko`
- `data/silver_ko`
- `data/gold_corpus_ko`

그 외 큰 데이터나 복원용 자료는 아래 Drive 링크를 사용하면 됩니다.

- [PBS external data folder](https://drive.google.com/drive/folders/136wfeJbcpst7iO3ZwBbwhzpbwMo_WiSh?usp=sharing)

## Git에 다시 넣지 말 것

- `.env`
- `artifacts/**`
- `data/bronze/raw_html/**`
- `data/bronze/source_bundles/**`
- customer/private 원본 문서
- 실험 리포트
- execution harness 재생성본
- task board / scorecard / local launcher 재생성본

## 편입 순서

1. 이 저장소의 `main`을 기준선으로 받습니다.
2. shared landing과 route namespace를 먼저 맞춥니다.
3. PBS 경로가 유지되는지 확인합니다.
4. partner 기능은 `/partner/*` 아래에서 붙입니다.
5. 추가 데이터가 필요할 때만 Drive에서 가져옵니다.
6. 마지막에 build와 최소 route regression을 확인합니다.

## 실행

```powershell
docker compose up -d --build app web qdrant
```

## 최소 검증

```powershell
npm --prefix presentation-ui run build
npm --prefix presentation-ui exec vitest run src/app/handoff.test.ts
.\.venv\Scripts\python.exe -m pytest tests/test_app_server.py tests/test_customer_pack_direct_viewer_route.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_app_viewers_routes.py -q -k "canonicalize_viewer_path or viewer_document_route_supports_entity_and_figure_paths or viewer_document_route_falls_back_to_normalized_sections_for_known_book or viewer_path_local_raw_html_fallback"
```
