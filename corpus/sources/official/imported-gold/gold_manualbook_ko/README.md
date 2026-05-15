# Gold Manualbook KO

OCP 공식 문서의 manualbook/playbook seed 영역이다.

## Current Files

- `playbook_documents.jsonl`: 29 line. 각 line은 book 단위 document JSON이다.
- `playbooks/*.json`: 29 files. `playbook_documents.jsonl`과 book slug 기준으로 1:1 대응한다.

## Current Decision

`playbooks/`는 중복처럼 보이지만 현재 브랜치에서는 아직 tracked 상태이며, 설정/뷰어/데이터룸/translation path에서 참조 후보로 남아 있다.
따라서 지금 바로 삭제하지 않는다.

정리 순서는 다음과 같다.

1. `playbook_documents.jsonl`을 canonical package entry로 삼는다.
2. per-book JSON은 legacy sidecar 또는 viewer fallback으로 표시한다.
3. 코드 참조를 resolver로 모은다.
4. 테스트 통과 후 per-book JSON 삭제 여부를 결정한다.

## Verified On 2026-05-15

- `playbooks/*.json`: 29 files
- `playbook_documents.jsonl`: 29 lines
- slug mismatch: none observed
