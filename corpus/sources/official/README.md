# Official Corpus Sources

Red Hat OpenShift 공식 문서 기반 seed/import 산출물 영역이다.

## Current State

현재 active 하위 폴더는 `imported-gold/`다. 이름에 `gold`가 들어가지만, 이것은 제품의 최종 Gold gate 통과 상태가 아니라 과거 translation/import lane의 산출물 이름이다.

## Cleanup Direction

공식 문서도 KMSC `course_pbs`처럼 다음 구조로 읽히게 정리한다.

- `chunks.jsonl`: 검색/답변용 chunk seed
- `assets/`: 공식 문서 이미지/evidence
- `manifests/`: source selection, approval, handoff manifest
- `quality/eval`: 제품 Gold 품질 판정과 평가 케이스

기존 `gold_manualbook_ko/playbooks/*.json`은 아직 코드 참조가 남아 있으므로 즉시 삭제하지 않는다.
