# v0.0.8 — Image-Based Server Deployment with Embedded Corpus

## 목표

PlayBookStudio v0.0.8은 서버에서 `git clone` 후 build하는 방식이 아니라, 사전에 빌드된 Docker image를 pull해서 바로 배포할 수 있는 구조를 만든다.

핵심 목표는 **app/web image 기반 배포 + app image 내부 corpus 포함 + one-shot seed job + 서버에는 compose/env만 배치**하는 것이다.

v0.0.8은 RAG 품질 개선 자체보다 배포 재현성을 개선하는 버전이다. 서버는 소스코드 전체를 clone하지 않아도 `docker compose pull`, `docker compose up`, `seed job`만으로 Studio, DB, Qdrant, corpus import가 동작해야 한다.

---

## 범위

### Core (P0 — v0.0.8 릴리스 기준)

- [x] `spec/v0.0.8/planner.md` 작성
- [x] app Docker image에 `corpus/` 포함
- [x] image-only compose 파일 추가
- [x] app/web image 이름을 env로 바꿀 수 있게 구성
- [x] GitHub Actions 기반 GHCR publish workflow 추가
- [x] 서버에서 repo clone 없이 compose/env만으로 실행 가능한 명령 문서화
- [x] official corpus seed job이 image 내부 `/app/corpus`를 읽도록 구성
- [x] course/study corpus seed job이 image 내부 `/app/corpus`를 읽도록 구성
- [x] KMSC 운영 문서 seed job이 image 내부 `/app/corpus/sources/kmsc/raw`를 일반 RAG로 import하도록 구성
- [x] Qdrant seed job이 image 내부 `/app/corpus`를 읽도록 구성
- [x] course/study asset import가 image 내부 embedded corpus asset을 찾도록 보정
- [x] Terminal WebSocket 8770 외부 노출 유지
- [x] compose config 검증
- [x] 변경분 커밋 및 원격 push

### Extras (P1 — 여유 있으면 포함)

- [ ] image tag versioning 예시 추가
- [ ] registry login/pull 절차 문서화
- [ ] corpus 포함 image와 외부 corpus volume 방식의 tradeoff 문서화
- [ ] 서버 최초 배포 체크리스트 추가

### 비범위 (v0.0.9 이후로 연기)

- GitHub Actions/CI pipeline 완성
- 사내 registry 생성/운영
- Kubernetes/OpenShift Deployment manifest 작성
- Helm chart 작성
- HTTPS 인증서와 사내 DNS 자동화
- DB/Qdrant backup/restore 자동화

---

## 배경

현재 테스트 서버 배포는 서버에 repository를 clone하고 서버에서 `docker compose build`를 수행하는 방식이다.

이 방식은 빠르게 테스트하기에는 쉽지만, 운영 배포 관점에서는 다음 문제가 있다.

| 영역 | 현재 상태 | v0.0.8 목표 |
|---|---|---|
| 코드 배포 | 서버에 git clone 필요 | 서버는 image pull만 수행 |
| 빌드 위치 | 서버에서 Docker build | 개발/CI 환경에서 build 후 registry push |
| corpus | repo clone으로 파일 존재 | app image에 corpus 포함 |
| 문서 seed | 서버 파일 시스템의 corpus 의존 | image 내부 `/app/corpus`에서 seed |
| 서버 구성 | repo 전체 필요 | compose/env만 필요 |
| 배포 속도 | 서버에서 npm/pip build로 오래 걸림 | image pull 중심으로 단축 |

---

## 도메인 기준

### Image 종류

```text
PLAYBOOKSTUDIO_APP_IMAGE   Python app/runtime/seed image
PLAYBOOKSTUDIO_WEB_IMAGE   nginx frontend image
postgres                   pgvector runtime DB
qdrant                     vector DB
```

### 배포 산출물

서버에 필요한 최소 파일은 다음으로 제한한다.

```text
docker-compose.image.yml
.env
```

선택적으로 운영 문서와 backup script를 둘 수 있다.

### Corpus 포함 기준

```text
/app/corpus/sources/official/imported-gold/gold_corpus_ko/chunks.jsonl
/app/corpus/sources/kmsc/raw/**/*.pptx
/app/corpus/sources/kmsc/parsed-preview/course_pbs/chunks.jsonl
/app/corpus/manifests/**
```

---

## 아키텍처

### 재사용 모듈

```text
deploy/Dockerfile
deploy/docker-compose.prod.yml
deploy/docker-compose.image.yml
deploy/DEPLOY.md
.env.production.example
src/play_book_studio/cli.py
src/play_book_studio/ingestion/official_gold_import.py
src/play_book_studio/course/qdrant_course.py
```

### 이미지 배포 흐름

```text
[Developer or CI]
        │
        ▼
docker build --target app
docker build --target web
        │
        ▼
docker push registry/.../playbookstudio-app:<tag>
docker push registry/.../playbookstudio-web:<tag>
        │
        ▼
[Server]
        │
        ▼
docker compose -f docker-compose.image.yml pull
docker compose -f docker-compose.image.yml up -d postgres qdrant
docker compose -f docker-compose.image.yml --profile seed up seed jobs
docker compose -f docker-compose.image.yml up -d app web
```

---

## 데이터 흐름

```text
app image
  /app/src
  /app/db
  /app/scripts
  /app/corpus
        │
        ▼
official-corpus-seed
        │
        ├── PostgreSQL document_chunks
        └── Qdrant openshift_docs
```

```text
web image
  nginx
  frontend dist
        │
        ▼
http://192.168.119.23:8080
        │
        ├── /api/* -> app:8765
        └── Terminal UI -> ws://192.168.119.23:8770
```

---

## 구현 계획

### Step 1. Planner 생성

- v0.0.1 형식으로 `spec/v0.0.8/planner.md`를 작성한다.

### Step 2. App Image에 Corpus 포함

- `deploy/Dockerfile` app stage에 `COPY corpus /app/corpus`를 추가한다.
- seed job이 bind mount 없이도 `/app/corpus`를 읽을 수 있어야 한다.

### Step 3. Image-Only Compose 추가

- `deploy/docker-compose.image.yml`를 추가한다.
- `app`, `db-migrate`, `official-corpus-seed`, `course-runtime-seed`, `qdrant-seed`는 `PLAYBOOKSTUDIO_APP_IMAGE`를 사용한다.
- `web`은 `PLAYBOOKSTUDIO_WEB_IMAGE`를 사용한다.
- `build:`는 사용하지 않는다.

### Step 4. Env Example 보강

- image 이름과 tag를 `.env.production.example`에 추가한다.
- cywell-host 기준 URL과 bind port를 유지한다.

### Step 5. 배포 문서화

- 서버에서 repo clone 없이 배포하는 절차를 `deploy/DEPLOY.md`에 추가한다.
- image build/push 명령과 server pull/up/seed 명령을 분리해서 적는다.

### Step 6. 검증

- `docker compose -f deploy/docker-compose.image.yml --env-file .env.production.example config --quiet`
- 관련 focused test 재실행

---

## API 확인 목록

| API | 목적 | v0.0.8 상태 |
|---|---|---|
| `/api/health` | app health | smoke |
| `/api/chat` | seeded corpus 기반 RAG | smoke |
| `/api/chat/stream` | streaming RAG | smoke |
| `/api/repositories/documents` | DB-backed documents | smoke |
| Terminal WebSocket `:8770` | OCP terminal | smoke |

---

## 보안 고려사항

1. image에는 `.env`, token, 개인 secret을 포함하지 않는다.
2. app image에 포함되는 것은 public/test corpus artifact로 제한한다.
3. `OCP_API_TOKEN`, DB password, registry credential은 서버 `.env` 또는 secret store로만 제공한다.
4. Postgres/Qdrant는 기본적으로 localhost bind를 유지한다.
5. Web/Terminal만 외부 접속이 필요하므로 `8080`, `8770`만 외부 bind한다.

---

## 회귀 / 스모크 테스트

### Compose Config

```powershell
docker compose -f deploy/docker-compose.image.yml --env-file .env.production.example config --quiet
```

### Build / Push 예시

```powershell
docker build -f deploy/Dockerfile --target app -t ghcr.io/jungyuoo/ocpops-playbookstudio-app:dev .
docker build -f deploy/Dockerfile --target web -t ghcr.io/jungyuoo/ocpops-playbookstudio-web:dev .
docker push ghcr.io/jungyuoo/ocpops-playbookstudio-app:dev
docker push ghcr.io/jungyuoo/ocpops-playbookstudio-web:dev
```

### GitHub Actions Publish

```text
Actions > Publish Docker Images > Run workflow > tag: dev
```

### Server Deploy 예시

```bash
docker compose -f docker-compose.image.yml --env-file .env pull
docker compose -f docker-compose.image.yml --env-file .env up -d postgres qdrant
docker compose -f docker-compose.image.yml --env-file .env --profile seed up official-corpus-seed kmsc-corpus-seed course-runtime-seed qdrant-seed
docker compose -f docker-compose.image.yml --env-file .env up -d app web
```

---

## 완료 기준 (DoD)

1. app image에 corpus가 포함되어 있다.
2. image-only compose에 `build:`가 없다.
3. 서버는 repo clone 없이 compose/env만으로 image pull 배포가 가능하다.
4. official corpus seed가 image 내부 `/app/corpus`를 사용한다.
5. course/study seed가 image 내부 `/app/corpus`를 사용한다.
6. course/study seed의 `data/course_pbs/assets/*` 참조가 embedded corpus asset으로 정상 import된다.
7. KMSC 운영 문서가 `study_docs` scope로 PostgreSQL/Qdrant 일반 RAG에 seed된다.
8. Qdrant seed가 image 내부 `/app/corpus`를 사용한다.
9. Terminal WebSocket 8770이 외부 노출된다.
10. compose config 검증이 통과한다.
11. 배포 문서에 build/push/server deploy 절차가 있다.
12. v0.0.8 브랜치가 원격에 push되어 있다.

---

## 작업 메모

- 2026-05-11: v0.0.7 변경분을 `feat/v0.0.7/chunk-quality-and-strict-terminal`에 커밋하고 push했다.
- 2026-05-11: v0.0.8 브랜치 `feat/v0.0.8/image-based-deploy`를 생성했다.
- 2026-05-11: app Docker image에 `corpus/`를 포함하도록 `deploy/Dockerfile`을 수정했다.
- 2026-05-11: `deploy/docker-compose.image.yml`를 추가해 서버가 repo clone 없이 image pull 기반으로 배포할 수 있게 했다.
- 2026-05-11: image-only seed job이 `/app/corpus`에서 official/course/Qdrant seed를 수행하도록 구성했다.
- 2026-05-11: `.env.production.example`에 image name, public URL, terminal URL, bind 값을 추가했다.
- 2026-05-11: `deploy/DEPLOY.md`에 image-only build/push/server deploy 절차를 추가했다.
- 2026-05-11: `.github/workflows/publish-images.yml`를 추가해 GHCR에 app/web image를 push하도록 구성했다.
- 2026-05-11: `docker compose -f deploy/docker-compose.image.yml --env-file .env.production.example config --quiet` 통과.
- 2026-05-11: `docker compose -f deploy/docker-compose.prod.yml --env-file .env.production.example config --quiet` 통과.
- 2026-05-11: GHCR image 기반 서버 seed 중 `course-runtime-seed`가 청크의 legacy `data/course_pbs/assets/*` 경로 때문에 asset을 찾지 못하는 것을 확인했다.
- 2026-05-11: `course-chunk-import`에서 legacy course asset 경로를 `/app/corpus/sources/kmsc/parsed-preview/course_pbs/assets/*`로 fallback 해석하도록 보정했다.
- 2026-05-11: KMSC 운영 문서 raw PPTX 12개가 image-only seed에서 일반 `study_docs` RAG로 import되지 않는 것을 확인했다.
- 2026-05-11: `kmsc-corpus-seed`를 추가해 KMSC 운영 문서를 `document_chunks(source_scope=study_docs)`와 `openshift_docs` Qdrant collection에 index하도록 구성했다.

