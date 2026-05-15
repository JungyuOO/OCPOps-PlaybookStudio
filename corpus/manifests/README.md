# Corpus Manifests

`corpus/manifests/`는 코퍼스 선정, 평가, handoff control 파일을 둔다.

## Folders

- `official/`: 공식 문서 source selection, approval, rebuild manifest.
- `course/`: KMSC course/learning 평가와 override manifest.
- `eval/`: retrieval/RAGAS/chat 품질 평가 케이스.
- `demo/`: demo scenario와 safe question set.
- `concepts/`: OCP concept synonym, 용어 보조 사전.

## Rule

manifest는 본문 코퍼스가 아니라 control plane이다. 어떤 문서를 쓸지, 어떤 질문으로 검증할지, 어떤 경로로 handoff할지를 고정한다.
