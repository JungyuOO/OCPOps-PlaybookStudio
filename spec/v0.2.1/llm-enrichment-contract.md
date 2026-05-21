# v0.2.1 LLM Enrichment Contract

## Purpose

Define how an LLM may be used to enrich official corpus chunks for retrieval.

The LLM is not a source of operational truth. It may only generate metadata and search-oriented text grounded in the source chunk.

## Boundary

Allowed:

- summarize source text
- extract topics, objects, operators, commands, errors, answer shapes
- generate realistic question phrasings for retrieval
- create `embedding_text` grounded in source text
- flag quality concerns

Not allowed:

- create new commands absent from source text
- recommend actions absent from source text
- mutate `source_url`, `viewer_path`, `chunk_id`
- convert warnings into instructions
- invent object/operator support
- include secrets, tokens, kubeconfig, or user-private runtime data

## Input Contract

The enrichment runner must provide deterministic context:

```json
{
  "schema_version": "llm_enrichment_input.v1",
  "chunk_id": "uuid",
  "book_slug": "advanced_networking",
  "section_path": ["..."],
  "chunk_type": "concept",
  "source_type": "official_doc",
  "source_url": "https://docs.redhat.com/...",
  "viewer_path": "/docs/...",
  "clean_text": "...",
  "deterministic_signals": {
    "commands": [],
    "objects": [],
    "object_aliases": [],
    "operators": [],
    "error_strings": [],
    "verification_hints": []
  }
}
```

`clean_text` must be produced before LLM enrichment. The LLM should never receive raw dirty command markers as the only source of truth.

## Output Contract

The LLM must return strict JSON:

```json
{
  "schema_version": "llm_enrichment_output.v1",
  "chunk_id": "uuid",
  "summary": "",
  "primary_topics": [],
  "secondary_topics": [],
  "objects": [],
  "object_aliases": [],
  "operators": [],
  "commands": [],
  "error_states": [],
  "intent_labels": [],
  "answer_shapes": [],
  "best_for_questions": [],
  "embedding_text": "",
  "quality_warnings": []
}
```

No markdown wrapper. No prose outside JSON.

## Field Rules

### summary

- 1-3 sentences.
- Must be grounded in `clean_text`.
- Should state what the chunk helps answer.

### primary_topics

- 1-5 topic labels.
- Specific beats broad.
- Bad: `openshift`, `cluster`, `configuration`
- Better: `pod network connectivity check`, `cluster network operator`, `ingress certificate`

### objects

Kubernetes/OpenShift resource names or operational objects.

`objects` must use canonical singular resource names. Do not output plural display words or abbreviations as primary objects.

Examples:

```text
Pod
Deployment
Route
NetworkPolicy
ClusterOperator
PodNetworkConnectivityCheck
PersistentVolumeClaim
PersistentVolume
```

Only include objects supported by the text.

Aliases and abbreviations must go into `object_aliases`.

Examples:

```text
PVC
PV
Pods
Nodes
Deployments
```

If the input contains `PVC`, output:

```json
{
  "objects": ["PersistentVolumeClaim"],
  "object_aliases": ["PVC"]
}
```

### operators

Only named Operators from text or deterministic signals.

Examples:

```text
Cluster Network Operator
Machine Config Operator
Ingress Operator
```

### commands

Commands must be exact or normalized from grounded source command text.

Allowed:

```text
oc get pods
oc describe pod
oc logs
```

Rejected:

```text
oc delete pod --all
kubectl ...
```

Unless the command appears in the source and passes validator policy.

### intent_labels

Intent labels describe retrievable task fit.

Examples:

```text
explain_concept
find_status_command
diagnose_connectivity
verify_operator_status
compare_resources
configure_policy
```

### answer_shapes

Allowed values:

```text
definition
step_by_step
command_lookup
diagnosis
comparison
warning
verification_checklist
configuration_example
no_answer
```

### best_for_questions

3-8 natural questions the chunk can actually answer.

Rules:

- Korean user phrasing is preferred for Korean corpus.
- Include common operational wording.
- Do not overfit to one keyword.
- Do not include questions the chunk cannot answer directly.

Examples:

```text
Pod 네트워크 연결 확인 결과는 어디에 저장돼?
Cluster Network Operator가 연결 테스트를 어떻게 실행해?
PodNetworkConnectivityCheck는 어떤 상황에서 봐야 해?
```

### embedding_text

Should be concise but richer than raw text:

```text
<section path>
<grounded summary>
Objects: ...
Operators: ...
Commands: ...
Good questions: ...
```

Length target:

```text
300-1200 Korean characters
```

Hard limit:

```text
2000 characters
```

## Prompt Requirements

The prompt must state:

- Use only the provided chunk.
- Preserve chunk identity.
- Do not invent commands.
- Return JSON only.
- If the chunk is navigation-only, mark `quality_warnings`.
- If source is insufficient, emit fewer fields rather than guessing.

## Validator Handoff

The LLM output is not accepted until deterministic validation passes.

Validator must check:

- schema version
- required keys
- source identity preservation
- command grounding
- dirty marker removal
- field length
- enum membership
- `best_for_questions` count
- unsupported object/operator warnings
- canonical object names vs aliases/plurals

Rejected output should be stored as a validation failure artifact, not silently fixed by another LLM call.

## Safety Policy

Risky commands must be tagged or rejected.

Risk classes:

```text
read_only
write
delete
admin
debug
unknown
```

The enrichment step may preserve risky commands only when they are present in source text and the validator marks them with risk metadata. Answer generation later decides whether to show them.

## Non-Goals

- no answer generation
- no user-specific runtime context
- no DB write
- no Qdrant upsert
- no pgvector insert
- no production prompt change
