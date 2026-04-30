# PlayBookStudio Server Deployment

This deployment keeps application images separate from runtime data.
The server must have Docker Compose, the repository files, `data/`,
`manifests/`, `artifacts/`, and the Qdrant volume or a Qdrant restore.

## Files

- `docker-compose.prod.yml` - production compose file.
- `.env.production.example` - copy to `.env.production` and fill secrets.
- `data/` - mounted read-only into the app container.
- `manifests/` - mounted read-only into the app container.
- `artifacts/` and `reports/` - mounted read-write for runtime output.
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

The app does not rebuild course vectors on every boot. Run the one-shot seed
service after restoring Qdrant for the first time, after changing
`data/course_pbs`, or when `course_pbs_ko` / `course_ops_learning_ko` is missing:

```powershell
docker compose -f docker-compose.prod.yml --env-file .env.production --profile seed run --rm qdrant-seed
```

This upserts:

- `data/course_pbs/chunks.jsonl` into `course_pbs_ko`
- `data/course_pbs/manifests/ops_learning_chunks_v1.jsonl` into `course_ops_learning_ko`

The command is idempotent for the same chunk IDs.

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
- `data/` and `manifests/` are mounted read-only so runtime writes cannot
  accidentally alter the source corpus on the server.
