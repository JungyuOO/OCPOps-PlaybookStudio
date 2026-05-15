# Silver KO

공식 문서 한국어 번역 draft와 cache 영역이다.

## Contents

- `translation_drafts/chunks.jsonl`
- `translation_drafts/normalized_docs.jsonl`
- `translation_drafts/playbook_documents.jsonl`
- `translation_drafts/playbooks/*.json`
- `translation_drafts/translation_cache/*.json`

## Decision

이 영역은 완료 코퍼스가 아니라 translation lane의 중간 산출물이다.
translation cache는 공식 문서를 다시 가져오거나 번역 draft를 재생성할 때 비용과 시간을 줄이는 용도이므로, 현재 merge 안정화 전에는 삭제하지 않는다.
