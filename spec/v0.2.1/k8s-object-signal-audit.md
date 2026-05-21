# v0.2.1 Kubernetes Object Signal Audit

## Purpose

Record the v0.2.1 inspection of `k8s_objects` in the current official corpus.

This is evidence for v0.2.2 audit implementation. It does not change corpus data, retrieval behavior, Qdrant, or database schema.

## Input

```text
corpus/sources/official/imported-gold/gold_corpus_ko/chunks.jsonl
```

Current extractor evidence:

```text
src/play_book_studio/ingestion/metadata_extraction.py
```

The extractor uses a regex containing aliases and plurals:

```text
Pod|Pods|Deployment|Deployments|...|Node|Nodes|...|PVC|PV
```

It stores matched text directly into `k8s_objects`.

## Summary

| Metric | Value |
| --- | ---: |
| total rows | 27,907 |
| rows with `k8s_objects` | 12,379 |
| rows with multiple objects | 4,218 |
| unique raw object values | 24 |
| unique canonical object values after simple mapping | 21 |
| rows with alias/abbreviation object values | 1,674 |
| rows with plural object values | 375 |
| object occurrences with alias/plural raw values | 2,038 |
| rows with unknown object values | 0 |
| rows with at least one object not directly present in current `text` | 6,982 |
| object occurrences not directly present in current `text` | 11,399 |

Interpretation:

- Unknown object strings are not currently the main problem.
- The main problems are alias/plural mixing and weak grounding metadata.
- Exact text grounding is conservative. Some not-grounded rows may come from translated terms, YAML/source manifests, or source-level metadata not visible in the current `text` field. They still need an explicit grounding status before being trusted by retrieval scoring.

## Raw Object Distribution

| Raw value | Count | Canonical target | Class |
| --- | ---: | --- | --- |
| `Pod` | 5,300 | `Pod` | canonical |
| `Service` | 1,782 | `Service` | canonical |
| `Node` | 1,466 | `Node` | canonical |
| `Namespace` | 1,266 | `Namespace` | canonical |
| `Secret` | 1,209 | `Secret` | canonical |
| `Ingress` | 1,043 | `Ingress` | canonical |
| `PVC` | 934 | `PersistentVolumeClaim` | alias |
| `MachineConfig` | 917 | `MachineConfig` | canonical |
| `Deployment` | 796 | `Deployment` | canonical |
| `PV` | 721 | `PersistentVolume` | alias |
| `ConfigMap` | 646 | `ConfigMap` | canonical |
| `MachineConfigPool` | 515 | `MachineConfigPool` | canonical |
| `DaemonSet` | 410 | `DaemonSet` | canonical |
| `Route` | 336 | `Route` | canonical |
| `DeploymentConfig` | 276 | `DeploymentConfig` | canonical |
| `ReplicaSet` | 226 | `ReplicaSet` | canonical |
| `Deployments` | 217 | `Deployment` | alias/plural |
| `Job` | 197 | `Job` | canonical |
| `StatefulSet` | 191 | `StatefulSet` | canonical |
| `ClusterVersion` | 166 | `ClusterVersion` | canonical |
| `Pods` | 103 | `Pod` | alias/plural |
| `Project` | 101 | `Project` | canonical |
| `Nodes` | 63 | `Node` | alias/plural |
| `CronJob` | 60 | `CronJob` | canonical |

## Canonicalized Distribution

| Canonical object | Count |
| --- | ---: |
| `Pod` | 5,403 |
| `Service` | 1,782 |
| `Node` | 1,529 |
| `Namespace` | 1,266 |
| `Secret` | 1,209 |
| `Ingress` | 1,043 |
| `Deployment` | 1,013 |
| `PersistentVolumeClaim` | 934 |
| `MachineConfig` | 917 |
| `PersistentVolume` | 721 |
| `ConfigMap` | 646 |
| `MachineConfigPool` | 515 |
| `DaemonSet` | 410 |
| `Route` | 336 |
| `DeploymentConfig` | 276 |
| `ReplicaSet` | 226 |
| `Job` | 197 |
| `StatefulSet` | 191 |
| `ClusterVersion` | 166 |
| `Project` | 101 |
| `CronJob` | 60 |

## Direct Text Grounding Check

Method:

- For each row, check whether each raw `k8s_objects` value appears literally in the row's current `text`.
- This is intentionally conservative and does not account for translation equivalents, source manifest metadata, or YAML kind normalization.

Result:

```text
rows_with_not_grounded_object = 6,982
object_occurrences_not_directly_grounded = 11,399
```

The row-level metric answers "how many chunks have at least one weak object signal." The occurrence-level metric answers "how many individual object labels need grounding review." v0.2.2 should report both, because a single row can contain several object labels and only some of them may be grounded.

Top direct-not-grounded values:

| Object | Not directly grounded | Directly grounded |
| --- | ---: | ---: |
| `Pod` | 1,883 | 3,417 |
| `Service` | 1,062 | 720 |
| `Namespace` | 859 | 407 |
| `Node` | 667 | 799 |
| `Secret` | 607 | 602 |
| `MachineConfig` | 598 | 319 |
| `Deployment` | 584 | 212 |
| `ConfigMap` | 413 | 233 |
| `PVC` | 403 | 531 |
| `DaemonSet` | 347 | 63 |
| `MachineConfigPool` | 314 | 201 |
| `Ingress` | 308 | 735 |
| `PV` | 276 | 445 |
| `DeploymentConfig` | 226 | 50 |
| `Route` | 188 | 148 |
| `Deployments` | 186 | 31 |
| `ReplicaSet` | 171 | 55 |
| `StatefulSet` | 163 | 28 |
| `Job` | 138 | 59 |
| `ClusterVersion` | 129 | 37 |
| `Pods` | 71 | 32 |
| `Project` | 57 | 44 |
| `CronJob` | 48 | 12 |
| `Nodes` | 32 | 31 |

## Examples

Common multi-object combinations:

| Count | Raw object combination |
| ---: | --- |
| 189 | `Pod`, `Namespace` |
| 187 | `Pod`, `Node` |
| 157 | `Node`, `Secret` |
| 121 | `Service`, `Pod` |
| 119 | `PV`, `PVC` |
| 117 | `PVC`, `PV` |
| 110 | `MachineConfig`, `Pod` |
| 92 | `Node`, `ClusterVersion` |
| 86 | `DaemonSet`, `Deployment`, `Pod` |
| 84 | `ConfigMap`, `Pod` |

Top books containing object signals:

| book_slug | Rows with object signal |
| --- | ---: |
| `nodes` | 2,504 |
| `backup_and_restore` | 1,228 |
| `storage` | 1,132 |
| `security_and_compliance` | 1,034 |
| `postinstallation_configuration` | 886 |
| `ingress_and_load_balancing` | 730 |
| `support` | 609 |
| `machine_configuration` | 526 |
| `authentication_and_authorization` | 512 |
| `operators` | 489 |

Example 1:

```text
chunk_id: 1240b232-cce8-57c4-ba81-d051cec796e7
book_slug: advanced_networking
section: 1.2. 연결 상태 점검 구현
object: Deployment
```

The text describes CNO deploying resources for connectivity checks, but does not literally contain `Deployment`. This may be conceptually related, but retrieval should not treat it as the same as a grounded `Deployment` resource unless the audit can explain the source of the object signal.

Example 2:

```text
chunk_id: cf660dfc-6046-5127-87c5-3a723cb17db1
book_slug: images
section: 8.2. Kubernetes 리소스 트리거
object: Deployments
```

The raw object value is plural. It should be canonicalized to `Deployment`, with `Deployments` retained only as an alias.

Example 3:

```text
chunk_id: 6d3a6e9a-4a92-5702-8dfc-7c3bd713578e
book_slug: backup_and_restore
section: 5.2.2.1. Changes from OADP 1.4 to 1.5
object: PVC
```

The raw object value is an abbreviation. It should be canonicalized to `PersistentVolumeClaim`, with `PVC` retained as an alias.

## Required v0.2.2 Behavior

The audit CLI must not treat current `k8s_objects` as trusted canonical metadata.

It should emit:

```json
{
  "objects": ["PersistentVolumeClaim"],
  "object_aliases": ["PVC"],
  "object_grounding": [
    {
      "object": "PersistentVolumeClaim",
      "aliases": ["PVC"],
      "status": "exact_text | alias_text | translated_text | command_kind | source_manifest | unverified",
      "evidence": "..."
    }
  ],
  "quality_warnings": []
}
```

Scoring rules:

- `objects` must be canonical singular names.
- aliases must never be primary metadata filter keys.
- `unverified` object signals must not receive strong retrieval boost.
- object values from source manifests must be marked as `source_manifest`, not silently treated as text-grounded.
- translated terms such as Korean "포드", "서비스", "배포", "노드" need a separate translation-equivalence map.

## Required Validator Checks

v0.2.2 validator should fail or warn when:

- raw object value is plural and not canonicalized.
- raw object value is an abbreviation and not split into canonical object plus alias.
- object is unknown to the canonical map.
- object is not grounded by text, command/YAML `kind`, source manifest, or approved translation-equivalence map.
- query object and chunk object would compare alias to canonical without normalization.

## Handoff

This audit strengthens the v0.2.1 conclusion:

RAG data quality problems are not limited to missing `embedding_text` and dirty commands. Existing metadata fields like `k8s_objects` also need canonicalization, alias preservation, and grounding status before they can safely drive retrieval.
