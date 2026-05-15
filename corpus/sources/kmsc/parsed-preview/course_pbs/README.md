# Course PBS Package

KMSC 고객/운영 문서를 운영 학습/위키 코퍼스로 쓰기 위해 만든 seed 패키지다.

## Contents

- `chunks.jsonl`: 523개 chunk seed. `facets`, `image_attachments`, `related_official_docs`, `quality_score`, `provenance` 등을 포함한다.
- `assets/`: 775개 이미지 evidence. 다이어그램, 콘솔 출력, 표, 테스트 화면 등 chunk의 시각 근거다.
- `manifests/course_v1.json`: course/stage/tour 구조.
- `manifests/ops_learning_chunks_v1.jsonl`: 운영 학습용 chunk projection.
- `manifests/ops_learning_guides_v1.json`: beginner/operator guide와 step 구성.

## Why This Is The Reference

이 패키지는 `chunks + assets + manifests`가 같은 경계 안에 있고, chunk가 asset evidence와 guide manifest로 이어진다.
공식 문서 패키지도 이 구조를 기준으로 정리한다.

## Runtime Boundary

이 폴더는 seed/import source다. 서비스에서 직접 이 폴더를 truth로 삼는 대신, import 후 PostgreSQL/Qdrant/storage projection을 사용한다.
