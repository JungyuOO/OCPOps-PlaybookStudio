# PlayBookStudio Server Deployment

This deployment keeps application images separate from runtime data.
The server must have Docker Compose, the repository files, PostgreSQL,
Qdrant, and the writable runtime directories used by the app. Seed/import
inputs under `corpus/` are only required when
running one-shot seed services.

## Files

- `deploy/docker-compose.prod.yml` - production compose file.
- `.env.production.example` - copy to `.env.production` and fill secrets.
- `artifacts/`, `storage/`, and `reports/` - mounted read-write for runtime output.
- `corpus/` - mounted read-only into seed/import services.
- PostgreSQL volume - defaults to `ocpops_playbookstudio_postgres_data`.
- Qdrant volume - defaults to `ocp-rag-chatbot_qdrant_storage`.

The app image does not copy `corpus/`. Keep this
directories on the server only when you need to run seed/import services.

## First Run

```powershell
Copy-Item .env.production.example .env.production
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production up -d --build
```

Then run seed/import jobs when the server has the seed input directories:

```powershell
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production --profile seed run --rm course-runtime-seed
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production --profile seed run --rm official-corpus-seed
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production --profile seed run --rm kmsc-corpus-seed
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production --profile seed run --rm qdrant-seed
```

Then verify:

```powershell
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production ps
Invoke-RestMethod http://127.0.0.1:8080/api/health
Invoke-RestMethod http://127.0.0.1:6335/collections
```

Expected Qdrant collections for the current dataset:

- `openshift_docs`
- `course_pbs_ko`
- `course_ops_learning_ko`

`openshift_docs` should include official corpus chunks plus KMSC study document
chunks. Official-only count should match:

```powershell
(Get-Content corpus\sources\official\imported-gold\gold_corpus_ko\chunks.jsonl | Measure-Object -Line).Lines
```

## Seed Course Qdrant Data

The app does not rebuild corpus/course vectors on every boot. Run one-shot seed
services after restoring Qdrant for the first time, after changing source data,
or when a collection is missing.

For course runtime rows and assets in PostgreSQL:

```powershell
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production --profile seed run --rm course-runtime-seed
```

For the official OpenShift corpus, this imports `corpus/sources/official/imported-gold/gold_corpus_ko/chunks.jsonl`
into PostgreSQL and indexes/refreshes Qdrant payloads for the `official_docs`
scope:

```powershell
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production --profile seed run --rm official-corpus-seed
```

For KMSC operational/study documents, this imports `corpus/sources/kmsc/raw`
into PostgreSQL with `source_scope=study_docs` and indexes the chunks into
`openshift_docs`:

```powershell
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production --profile seed run --rm kmsc-corpus-seed
```

For course vectors:

```powershell
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production --profile seed run --rm qdrant-seed
```

This upserts:

- `corpus/sources/kmsc/parsed-preview/course_pbs/chunks.jsonl` into `course_pbs_ko`
- `corpus/sources/kmsc/parsed-preview/course_pbs/manifests/ops_learning_chunks_v1.jsonl` into `course_ops_learning_ko`

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

Or publish from GitHub Actions without a local GitHub token:

```text
Actions > Publish Docker Images > Run workflow > tag: dev
```

The workflow pushes both images to GHCR:

```text
ghcr.io/jungyuoo/ocpops-playbookstudio-app:dev
ghcr.io/jungyuoo/ocpops-playbookstudio-web:dev
```

On the server, place only these files in a deployment directory:

```text
docker-compose.image.yml
.env
```

Set the image names and secrets in `.env`:

```env
PLAYBOOKSTUDIO_APP_IMAGE=ghcr.io/jungyuoo/ocpops-playbookstudio-app:dev
PLAYBOOKSTUDIO_WEB_IMAGE=ghcr.io/jungyuoo/ocpops-playbookstudio-web:dev
PLAYBOOKSTUDIO_PUBLIC_URL=http://192.168.119.23:8080
TERMINAL_PUBLIC_WS_URL=ws://192.168.119.23:8770
OCP_API_TOKEN=replace-with-remote-sno-token
```

Pull and start database services:

```bash
docker compose -f docker-compose.image.yml --env-file .env pull
docker compose -f docker-compose.image.yml --env-file .env up -d postgres qdrant
```

Run one-shot corpus seed jobs:

```bash
docker compose -f docker-compose.image.yml --env-file .env --profile seed up official-corpus-seed kmsc-corpus-seed course-runtime-seed qdrant-seed
```

Start app and web:

```bash
docker compose -f docker-compose.image.yml --env-file .env up -d app web
docker compose -f docker-compose.image.yml --env-file .env ps
```

## Notes

- `web` is exposed by `WEB_BIND`, default `0.0.0.0:8080`.
- Terminal WebSocket is exposed by `TERMINAL_WS_BIND`, default `0.0.0.0:8770`.
- Qdrant binds to localhost by default for safety.
- The app uses Qdrant over the internal Docker network: `http://qdrant:6333`.
- The production app container no longer mounts `corpus/`; that directory is
  only a seed/import input.
- The image-only app container includes `corpus/` at `/app/corpus`; do not put
  `.env` or other secret files in the image.
- For the cywell-host deployment, copy `.env.production.example` to
  `.env.production`, keep `PLAYBOOKSTUDIO_PUBLIC_URL=http://192.168.119.23:8080`,
  and replace only secrets such as `POSTGRES_PASSWORD`, `DATABASE_URL`, and
  `OCP_API_TOKEN`.

