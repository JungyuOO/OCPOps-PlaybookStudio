# KMSC Corpus Sources

KMSC 고객/운영 문서 기반 코퍼스 seed 영역이다.

현재 기준 패키지는 `parsed-preview/course_pbs/`다. 이 패키지는 단순 파일 모음이 아니라 `chunks.jsonl`, `assets/`, `manifests/`가 같이 있는 비교적 정리된 레퍼런스 모델이다.

## Current Package

- `parsed-preview/course_pbs/chunks.jsonl`: 고객/운영 문서에서 만든 chunk seed.
- `parsed-preview/course_pbs/assets/`: PPT/문서에서 추출된 이미지 evidence.
- `parsed-preview/course_pbs/manifests/`: course, learning guide, learning chunk control manifest.

## Cleanup Rule

KMSC 패키지는 공식 문서 패키지 정리의 참고 모델이다. 임의 삭제하지 않고, 경로 변경이 필요하면 course API, tests, asset resolver를 같이 바꾼다.
