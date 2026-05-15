# Official Imported Gold

OCP 공식 문서 번역/정규화/import 산출물이 모여 있는 legacy seed 영역이다.

`Gold`라는 이름은 현재 제품의 최종 Gold 품질 판정을 뜻하지 않는다. 이 폴더는 과거 translation lane에서 만들어진 import seed, draft, retrieval corpus가 섞여 있는 transitional 영역이다.

## Folders

- `gold_candidate_books/`: full rebuild 후보 manifest.
- `gold_corpus_ko/`: BM25/chunk retrieval seed.
- `gold_manualbook_ko/`: manualbook/playbook document seed. JSONL과 per-book JSON이 같이 있음.
- `silver_ko/`: 번역 draft와 translation cache.

## Cleanup Rule

1. 먼저 어떤 코드가 어떤 경로를 읽는지 resolver로 고정한다.
2. KMSC package model에 맞춰 package manifest를 추가한다.
3. 참조가 0개가 된 legacy 파일만 삭제하거나 이동한다.
