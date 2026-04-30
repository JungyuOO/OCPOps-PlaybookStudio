# Corpus Seed Area

`corpus/` is the local seed/import area for source material. Runtime code should not treat this directory as the source of truth after data has been imported.

Target layout:

```text
corpus/
├─ sources/
│  ├─ official/
│  ├─ kmsc/
│  └─ demo/
└─ manifests/
   ├─ official/
   ├─ kmsc/
   └─ eval/
```

Migration targets:

- `study-docs/**` -> `corpus/sources/kmsc/raw/**`
- selected `data/gold_*` -> `corpus/sources/official/imported-gold/**`
- eval JSONL manifests -> `corpus/manifests/eval/**`

Operational rule:

- Import from `corpus/**` into PostgreSQL.
- Rebuild Qdrant from PostgreSQL chunks.
- Serve runtime answers from PostgreSQL/Qdrant/storage, not from this folder.
