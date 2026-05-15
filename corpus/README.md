# Corpus Seed Area

`corpus/`는 원천 자료, import seed, 평가/선정 manifest를 보관하는 작업 영역이다.
런타임의 진실 소스는 import 이후 PostgreSQL, Qdrant, storage이며, `corpus/` 자체가 런타임 DB 역할을 하면 안 된다.

## Current Layout

```text
corpus/
|-- sources/      # import 가능한 원천/seed 패키지
|-- manifests/    # 선정, 평가, handoff control manifest
`-- data/         # wiki sidecar/evidence 산출물. 런타임 truth 아님
```

## Package Reference

현재 가장 정리된 레퍼런스는 KMSC 고객 데이터 패키지다.

```text
corpus/sources/kmsc/parsed-preview/course_pbs/
|-- chunks.jsonl
|-- assets/
`-- manifests/
    |-- course_v1.json
    |-- ops_learning_chunks_v1.jsonl
    `-- ops_learning_guides_v1.json
```

공식 문서 쪽도 장기적으로 이 모델을 따른다. 즉, 한 패키지 안에서 `chunks`, `assets`, `manifests`, `quality/eval handoff`의 역할이 보이게 정리한다.

## Operating Rules

- Import는 `corpus/**`에서 시작할 수 있다.
- Import 후 서비스 기준 데이터는 PostgreSQL에 둔다.
- Qdrant는 PostgreSQL chunk/corpus projection으로 재생성한다.
- 원본, 파싱본, chunk, manifest, asset evidence를 섞어 두지 않는다.
- `Gold`라는 폴더명이 있더라도 제품의 최종 Gold 품질 통과를 뜻한다고 자동 해석하지 않는다. legacy/import seed이면 그렇게 표시한다.
- 삭제/rename은 코드 참조와 테스트를 먼저 확인한 뒤 한다.

## Active Subfolders

- `sources/official`: OCP 공식 문서 seed/import 산출물.
- `sources/kmsc`: KMSC 고객/운영 문서 seed 패키지.
- `manifests`: 공식/고객/eval/데모 control manifest.
- `data`: wiki asset/relation/runtime sidecar 산출물.
