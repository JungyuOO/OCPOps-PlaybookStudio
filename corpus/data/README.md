# Corpus Data Sidecars

`corpus/data/`는 wiki asset, relation, runtime book sidecar 산출물을 둔다.

## Current Folders

- `wiki_assets/`: 공식 문서/wiki viewer용 이미지와 asset evidence 산출물.
- `wiki_relations/`: entity, figure, section relation sidecar.
- `wiki_runtime_books/`: runtime book manifest sidecar.

## Boundary

이 폴더는 런타임 truth가 아니다. PostgreSQL/Qdrant/storage로 import되거나 viewer build에 사용되는 sidecar로 취급한다.
삭제/이동 전에는 viewer, relation builder, source resolver 참조를 먼저 확인한다.
