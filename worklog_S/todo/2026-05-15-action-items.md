# 2026-05-15 할 일

## 오늘의 우선순위

새 기능을 크게 벌리기 전에, 먼저 코퍼스 구조와 메타데이터 전략을 팀이 이해 가능한 형태로 고정한다.

J의 `spec/v0.1.4` 확인 후 오늘 플랜은 아래 문서를 우선 기준으로 한다.

- `worklog_S/todo/2026-05-15-plan-after-j-v014-spec.md`

2026-05-15 09:58 재확인 결과, J 플래너에 `text 4계층`, `encoding/UTF-8`, `Qdrant rebuild` 원칙이 추가됐다. 이 세 항목은 오늘 gap audit에 포함한다.

실행 순서:

0. 완료: J `spec/v0.1.4` 3개 문서 훑기
1. 완료: 현재 데이터 인벤토리 baseline 고정
2. 완료: corpus 폴더 구조를 v0.1.4 source/import/evidence 계약에 맞춰 정리
3. 완료: v0.1.4 용어 브릿지 작성
4. `docs/metadata-strategy.md` 작성
5. 실제 데이터 3종 dry-run mapping
6. 현재 구조와 v0.1.4 gap audit
7. `db/migrations/0009_corpus_layer.sql` 초안 작성
8. Qdrant payload projection 함수 초안 작성
9. Compatibility path 작성
10. Smoke test 작성
11. Metadata Spine 문서를 v0.1.4 용어로 재정렬
12. S/J handoff 계약 정리
13. Wiki Library count/label 혼동 수정
14. 업로드 pipeline/Gold 품질 검증 재개

이 순서를 바꾸려면 새 근거가 있어야 한다. 특히 1~6을 건너뛰고 UI나 Gold 수리 구현으로 바로 가지 않는다.

Inventory baseline:

- `worklog_S/todo/2026-05-15-inventory-baseline.md`

Term bridge:

- `docs/corpus/V014_TERM_BRIDGE.md`

MVP guardrails:

- `worklog_S/todo/2026-05-15-v014-mvp-guardrails.md`

## P0. corpus 폴더 구조 정리 마무리

목표:

- `corpus/`를 보고 무엇이 source, manifest, sidecar/evidence인지 바로 알 수 있게 만든다.
- `Gold`라는 이름이 제품 Gold로 오해되지 않게 한다.
- KMSC clean package를 공식 reference로 삼고, official 쪽도 같은 패키징 방향을 따른다.

확인할 것:

- `corpus/sources/official/`
  - 현재 공식 데이터 source-first 위치가 맞는지
  - legacy `imported-gold`가 제품 Gold처럼 보이지 않는지
- `corpus/sources/kmsc/parsed-preview/course_pbs/`
  - clean customer corpus package reference로 문서화됐는지
- `corpus/manifests/`
  - handoff/control 역할이 README에 설명됐는지
- `corpus/data/`
  - runtime truth가 아니라 sidecar/evidence임이 설명됐는지

검증:

- `git ls-files corpus`
- `rg "corpus/|data/wiki_|imported-gold|gold_corpus_ko|course_pbs" src tests apps deploy`
- 빈 폴더 확인
- README 누락 확인

완료 기준:

- 팀원이 `corpus/`만 보고 어디에 무엇을 넣어야 하는지 설명할 수 있다.
- `official`, `kmsc`, `manifests`, `data`의 역할이 겹쳐 보이지 않는다.
- `Gold` 이름 때문에 runtime Gold와 legacy seed가 혼동되지 않는다.

## P0. Metadata Spine 전략 확정

목표:

- S가 만드는 코퍼스가 J 챗봇이 검색/답변에 쓸 수 있는 형태가 되게 한다.
- chunk마다 answer-ready metadata를 만든다.

필수 메타:

- `source_scope`
- `document_source_id`
- `parsed_document_id`
- `chunk_id`
- `topic`
- `semantic_role`
- `k8s_objects`
- `cli_commands`
- `error_strings`
- `verification_hints`
- `answerable_questions`
- `metadata_confidence`

검증:

- SCC/RBAC/Route/Deployment/Pod 같은 OCP 객체가 chunk metadata에 잡히는지
- `oc`, `kubectl`, `helm`, `curl` 명령이 잡히는지
- 에러 문자열과 확인 명령이 분리되는지
- Qdrant payload와 DB metadata가 같은 의미를 담는지

완료 기준:

- 최소 official, KMSC/customer, user upload 각 1개 샘플에서 metadata coverage를 설명할 수 있다.
- J에게 "이 chunk가 어떤 질문에 답할 수 있는지"를 넘길 수 있다.

## P0. J handoff 계약 정리

목표:

- S와 J가 서로 책임을 미루지 않게, 실패 원인을 분류하는 계약을 만든다.

S가 넘길 것:

- `corpus_version`
- scope별 document/chunk/gold/topology count
- metadata coverage
- golden questions
- expected chunk ids
- known blockers

J가 남길 것:

- user query
- rewritten query
- selected chunk ids
- reranker result
- citations
- response kind
- pipeline trace

실패 분류:

- 정답 chunk가 코퍼스에 없음: S 문제
- 정답 chunk가 있는데 검색 상위에 없음: S/J 공동 문제
- 정답 chunk가 선택됐는데 답변이 틀림: J 문제
- citation이 틀림: S/J 공동 문제

완료 기준:

- golden question 하나를 기준으로 S expected chunk와 J selected chunk를 비교할 수 있다.
- 챗봇이 틀렸을 때 "누가 감으로 고친다"가 아니라 gap 종류로 분류된다.

## P1. Wiki Library count/label 혼동 수정

목표:

- `29개`와 `34권` 같은 질문이 다시 나오지 않게 한다.

해야 할 것:

- 공식 원천 문서 count와 운영 위키 output count를 UI에서 분리한다.
- `Book`, `Document`, `Gold`, `Recovery`, `Candidate`를 섞어 쓰지 않는다.
- count 옆에 source 의미를 짧게 표시한다.

권장 표기:

- `공식 원천 문서 29개`
- `Gold Ready 23권`
- `수리 필요 11건`
- `공식 후보 84개`
- `전체 공식 카탈로그 113개`

상세 이슈:

- `worklog_S/todo/2026-05-15-wiki-library-count-mismatch.md`

완료 기준:

- 사용자가 "왜 레포는 29인데 화면은 34냐"라고 물었을 때 화면 자체에서 답을 알 수 있다.

## P1. 업로드 pipeline / Gold 품질 검증 재개

목표:

- 업로드 후 단계 UI가 실제 서버 이벤트와 품질 판정만 반영하게 한다.
- Gold가 사람이 읽을 수 있는 지식 데이터 품질을 의미하게 한다.

해야 할 것:

- 최근 업로드 대표 PDF를 원본과 Reader 결과로 비교한다.
- pipeline event ledger가 reload 후에도 같은 상태를 복원하는지 확인한다.
- `code_loss`, `page_stub`, 단어 깨짐, 표/문장 손실을 품질 gate에서 잡는다.
- 수리 후 chunk, Qdrant, topology, quality snapshot이 실제로 다시 만들어졌는지 확인한다.

완료 기준:

- 새 업로드 1건이 실제 이벤트 순서대로 진행된다.
- 실패/보류 케이스가 마지막 실제 단계에서 멈춘다.
- Reader 품질이 원본 대비 납득 가능하다.
- Gold 상태가 단순 저장 성공과 혼동되지 않는다.

## P2. 공식 원천 데이터 재패키징 전략

목표:

- 공식 홈페이지 HTML, 공식 GitHub repo, AsciiDoc, 번역 사전, 이미지 asset이 어떤 기준으로 쓰이는지 명확히 한다.

정리할 질문:

- 공식 source truth는 어디인가?
- 공식 GitHub repo에서 AsciiDoc을 가져오는 흐름이 현재 살아 있는가?
- 한글 번역 고유명사 사전은 어디에 남아 있고, 지금 pipeline에서 쓰이는가?
- 이미지/asset은 어디에 저장되고 Reader/Topology/Chat에서 어떻게 연결되는가?

완료 기준:

- J에게 "왜 json/jsonl 산출물을 남기는지" 설명 가능하다.
- S가 "왜 Gold corpus 품질이 나쁜지" 원인 단위로 추적 가능하다.
- 공식 데이터 재수집이 필요하다면 어떤 단계부터 다시 해야 하는지 말할 수 있다.

## 오늘 하지 않을 것

- 새 데이터를 무작정 더 쌓기
- topology 대형 고도화부터 다시 시작하기
- 품질 기준 없이 Gold 숫자만 늘리기
- J와 계약 없이 챗봇 쪽까지 S가 임의로 건드리기
