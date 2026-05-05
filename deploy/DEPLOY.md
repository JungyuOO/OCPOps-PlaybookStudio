# PlayBookStudio Server Deployment

This deployment keeps application images separate from runtime data.
The server must have Docker Compose, the repository files, PostgreSQL,
Qdrant, and the writable runtime directories used by the app. Seed/import
inputs such as `data/`, `corpus/`, and `manifests/` are only required when
running one-shot seed services.

## Files

- `docker-compose.prod.yml` - production compose file.
- `.env.production.example` - copy to `.env.production` and fill secrets.
- `artifacts/`, `storage/`, and `reports/` - mounted read-write for runtime output.
- `manifests/` - temporarily mounted read-only into the app for remaining UI source-manifest compatibility.
- `data/`, `corpus/`, and `manifests/` - mounted read-only into seed/import services.
- PostgreSQL volume - defaults to `ocpops_playbookstudio_postgres_data`.
- Qdrant volume - defaults to `ocp-rag-chatbot_qdrant_storage`.

## First Run

```powershell
Copy-Item .env.production.example .env.production
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Then verify:

```powershell
docker compose -f docker-compose.prod.yml --env-file .env.production ps
Invoke-RestMethod http://127.0.0.1:8080/api/health
Invoke-RestMethod http://127.0.0.1:6335/collections
```

Expected Qdrant collections for the current dataset:

- `openshift_docs`
- `course_pbs_ko`
- `course_ops_learning_ko`

`openshift_docs` should have the same count as:

```powershell
(Get-Content data\gold_corpus_ko\chunks.jsonl | Measure-Object -Line).Lines
```

## Seed Course Qdrant Data

The app does not rebuild corpus/course vectors on every boot. Run one-shot seed
services after restoring Qdrant for the first time, after changing source data,
or when a collection is missing.

For the official OpenShift corpus, this imports `data/gold_corpus_ko/chunks.jsonl`
into PostgreSQL and indexes/refreshes Qdrant payloads for the `official_docs`
scope:

```powershell
docker compose -f docker-compose.prod.yml --env-file .env.production --profile seed run --rm official-corpus-seed
```

For course vectors:

```powershell
docker compose -f docker-compose.prod.yml --env-file .env.production --profile seed run --rm qdrant-seed
```

This upserts:

- `data/course_pbs/chunks.jsonl` into `course_pbs_ko`
- `data/course_pbs/manifests/ops_learning_chunks_v1.jsonl` into `course_ops_learning_ko`

The command is idempotent for the same chunk IDs.
The official corpus seed is also idempotent for the same chunk IDs and uses
`OFFICIAL_CORPUS_INDEX_LIMIT` / `OFFICIAL_CORPUS_REFRESH_LIMIT` to cap one run.

## Preserve Existing Qdrant Data

Do not set `QDRANT_RECREATE_COLLECTION=true` on the server unless you are
intentionally rebuilding the collection. Production defaults it to `false`.

To move the existing local Qdrant data, export/import the Docker volume, or
copy the volume directory using your server backup process. The volume name is:

```text
ocp-rag-chatbot_qdrant_storage
```

## Update Deployment

```powershell
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build app web
docker compose -f docker-compose.prod.yml --env-file .env.production ps
```

## Notes

- `web` is exposed by `WEB_BIND`, default `0.0.0.0:8080`.
- Qdrant binds to localhost by default for safety.
- The app uses Qdrant over the internal Docker network: `http://qdrant:6333`.
- The production app container no longer mounts `data/` or `corpus/`; those
  directories are seed/import inputs. `manifests/` remains mounted read-only
  until the remaining source-manifest UI paths are fully DB-backed.
