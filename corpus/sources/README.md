# Corpus Sources

`corpus/sources/`는 import 가능한 원천 또는 seed 패키지를 둔다.

## Folders

- `official/`: Red Hat OpenShift 공식 문서 기반 seed/import 산출물.
- `kmsc/`: KMSC 고객/운영 문서 기반 seed 패키지.

## Rule

여기에 있는 파일은 "런타임 DB"가 아니라 "다시 import하거나 검증할 수 있는 패키지"여야 한다.
패키지 안에는 가능하면 다음 역할이 분리되어야 한다.

- source or normalized document
- chunks
- assets
- manifests
- quality/eval handoff
