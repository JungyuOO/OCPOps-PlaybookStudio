# PlayBookStudio Server Deployment

This deployment uses PostgreSQL with pgvector as the runtime RAG store.
Application images stay separate from runtime data. Seed/import inputs under
`corpus/` are only required when running one-shot seed services.

## Files

- `deploy/docker-compose.prod.yml` - production compose file.
- `.env.production.example` - copy to `.env.production` and fill secrets.
- `artifacts/`, `storage/`, and `reports/` - mounted read-write for runtime output.
- `corpus/` - mounted read-only into seed/import services.
- PostgreSQL volume - defaults to `ocpops_playbookstudio_postgres_data`.

## First Run

```powershell
Copy-Item .env.production.example .env.production
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production up -d --build
```

Run seed/import jobs when the server has the seed input directories:

```powershell
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production --profile seed run --rm course-runtime-seed
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production --profile seed run --rm official-corpus-seed
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production --profile seed run --rm kmsc-corpus-seed
```

Verify:

```powershell
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production ps
Invoke-RestMethod http://127.0.0.1:8080/api/health
```

The health payload should report:

- `vector_backend: pgvector`
- `db_corpus.ready: true`
- `embedding_index_parity: true`
- `stale_embedding_index_entries: 0`

## Seed Data

For course runtime rows and assets in PostgreSQL:

```powershell
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production --profile seed run --rm course-runtime-seed
```

For the official OpenShift corpus, this imports `corpus/sources/official/imported-gold/gold_corpus_ko/chunks.jsonl`
into PostgreSQL and writes embeddings into `chunk_embeddings`:

```powershell
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production --profile seed run --rm official-corpus-seed
```

For KMSC operational/study documents, this imports the tracked parsed course
chunks under `corpus/sources/kmsc/parsed-preview/course_pbs` with
`source_scope=study_docs` and writes embeddings into `chunk_embeddings`:

```powershell
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production --profile seed run --rm kmsc-corpus-seed
```

The import commands are idempotent for the same chunk IDs and embedding text.
`OFFICIAL_CORPUS_INDEX_LIMIT` caps one official seed run.

## Update Deployment

```powershell
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production up -d --build app web
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production ps
```

## Image-Only Deployment

Use this path when the server must not clone or build the repository. The app
image includes `/app/corpus`, so seed jobs can import official and course
documents from the image itself.

Build and push images from a developer or CI machine:

```powershell
docker build -f deploy/Dockerfile --target app -t ghcr.io/jungyuoo/ocpops-playbookstudio-app:dev .
docker build -f deploy/Dockerfile --target web -t ghcr.io/jungyuoo/ocpops-playbookstudio-web:dev .
docker push ghcr.io/jungyuoo/ocpops-playbookstudio-app:dev
docker push ghcr.io/jungyuoo/ocpops-playbookstudio-web:dev
```

On the server, place only these files in a deployment directory:

```text
docker-compose.image.yml
.env
```

Pull and start PostgreSQL:

```bash
docker compose -f docker-compose.image.yml --env-file .env pull
docker compose -f docker-compose.image.yml --env-file .env up -d postgres
```

Run one-shot corpus seed jobs:

```bash
docker compose -f docker-compose.image.yml --env-file .env --profile seed up official-corpus-seed kmsc-corpus-seed course-runtime-seed
```

Start app and web:

```bash
docker compose -f docker-compose.image.yml --env-file .env up -d app web
docker compose -f docker-compose.image.yml --env-file .env ps
```

## Notes

- `web` is exposed by `WEB_BIND`, default `0.0.0.0:8080`.
- Terminal WebSocket is exposed by `TERMINAL_WS_BIND`, default `0.0.0.0:8770`.
- The production app container no longer mounts `corpus/`; that directory is
  only a seed/import input.
- The image-only app container includes `corpus/` at `/app/corpus`; do not put
  `.env` or other secret files in the image.
