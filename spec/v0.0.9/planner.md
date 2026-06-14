# v0.0.9 — OpenShift In-Cluster Deployment

## 목표

PlayBookStudio v0.0.9는 `192.168.119.23` Ubuntu Docker 서버 배포를 테스트 기준으로 종료하고, 실제 OpenShift SNO 클러스터 내부에 GHCR image 기반으로 배포한다.

핵심 목표는 **`pbs-ocpops` namespace + app/web/postgres/qdrant in-cluster 배포 + one-shot seed job + Route 기반 Studio/Terminal 접속**이다.

사용자가 말한 `PBS-OCPOps`는 Kubernetes namespace 이름으로는 대문자를 사용할 수 없으므로 실제 namespace는 `pbs-ocpops`로 생성하고, label/display 용도로 `PBS-OCPOps`를 남긴다.

---

## 범위

### Core (P0 — v0.0.9 릴리스 기준)

- [x] `spec/v0.0.9/planner.md` 작성
- [x] OpenShift namespace manifest 작성
- [x] PostgreSQL Deployment/Service/PVC 작성
- [x] Qdrant Deployment/Service/PVC 작성
- [x] app Deployment/Service 작성
- [x] web Deployment/Service/Route 작성
- [x] Terminal WebSocket을 web Route 하위 `/terminal-ws/`로 프록시하도록 구성
- [x] seed Job manifest 작성
- [x] Studio Chat 실운영 추천 질문용 learning seed Job 작성
- [x] Secret/ConfigMap 적용 스크립트 작성
- [x] Ubuntu Docker compose 배포 중지/삭제 절차 작성
- [ ] 로컬 manifest 검증
- [ ] 변경분 커밋 및 원격 push
- [ ] `192.168.119.23` 서버에서 OCP apply 수행
- [ ] OpenShift Route 접속, Chat, KMSC RAG, Terminal 검증

### Extras (P1 — 여유 있으면 포함)

- [ ] Resource requests/limits 보수적으로 조정
- [ ] seed job 재실행 스크립트 추가
- [ ] 외부 DB/Qdrant 전환 가이드 추가
- [ ] Route hostname 고정 가이드 추가

### 비범위 (v0.0.10 이후)

- Helm chart
- GitOps/ArgoCD 운영화
- TLS 인증서 커스텀 도메인 자동화
- DB/Qdrant backup/restore 자동화
- raw KMSC PPTX 원본 배포

---

## 배경

v0.0.8에서는 GHCR image를 Ubuntu 서버에서 `docker compose`로 pull하여 배포했다. 그러나 실제 목표는 OCP 연결 서버 자체가 아니라 OpenShift 클러스터 내부에 PlayBookStudio를 배포하는 것이다.

따라서 v0.0.9는 Docker Compose 배포 산출물을 유지하되, OpenShift용 manifest를 별도로 추가한다.

---

## 도메인 기준

### Namespace

```text
requested display name: PBS-OCPOps
actual namespace:       pbs-ocpops
```

### Image

```text
ghcr.io/jungyuoo/ocpops-playbookstudio-app:dev
ghcr.io/jungyuoo/ocpops-playbookstudio-web:dev
pgvector/pgvector:pg16
qdrant/qdrant:latest
```

### In-cluster service names

```text
postgres:5432
qdrant:6333
app:8765
app:8770
web:80
```

### Public Route

```text
web Route:
  /              -> web nginx static UI
  /api/*         -> app:8765
  /terminal-ws/  -> app:8770
```

Terminal은 별도 8770 외부 포트를 열지 않고 OpenShift Route의 WebSocket upgrade를 사용한다.

---

## 아키텍처

```text
Browser
  |
  v
OpenShift Route (web)
  |
  v
web nginx
  |-- /assets, /studio -> static frontend
  |-- /api/*           -> app:8765
  `-- /terminal-ws/    -> app:8770

app
  |-- PostgreSQL -> postgres service
  `-- Qdrant     -> qdrant service
```

---

## 구현 계획

### Step 1. Same-Origin Terminal WebSocket

- `apps/web/src/pages/workspace/TerminalSessionPanel.tsx` 기본 WS URL을 `/terminal-ws/`로 변경한다.
- `deploy/nginx/default.conf`에 `/terminal-ws/` WebSocket proxy location을 추가한다.
- Docker 배포에서도 같은 방식으로 동작하므로 `:8770` 직접 접속 의존을 줄인다.

### Step 2. OpenShift Manifests

- `deploy/openshift/playbookstudio.yaml` 생성
- Namespace, ConfigMap, PVC, Deployment, Service, Route, seed Job을 한 파일에 둔다.
- Secret은 실제 token/password를 커밋하지 않기 위해 apply script에서 생성한다.

### Step 3. Apply Script

- `deploy/openshift/apply-playbookstudio.sh` 생성
- `oc new-project pbs-ocpops` 또는 `oc apply -f namespace` 수행
- 기존 Secret 재생성
- manifest apply
- seed job 재실행 옵션 제공

### Step 4. Ubuntu Docker 배포 정리

- `~/playbookstudio-image` compose 배포를 `down` 처리한다.
- volume은 명시 요청 전까지 삭제하지 않는다.
- image prune은 선택 사항으로 둔다.

### Step 5. 검증

- `oc get pods -n pbs-ocpops`
- `oc get route -n pbs-ocpops`
- `/api/health`
- Studio Chat에서 official/KMSC corpus 확인
- Terminal Session 연결 확인

---

## 완료 기준 (DoD)

1. `pbs-ocpops` namespace가 생성된다.
2. app/web/postgres/qdrant pod가 정상 기동한다.
3. web Route로 Studio에 접속된다.
4. `/api/health`가 `db_corpus.ready=true`를 반환한다.
5. official docs와 KMSC study docs가 seed된다.
6. KMSC ops learning guides가 `learning_paths`로 seed되어 Studio Chat 실운영 질문에 노출된다.
7. Terminal Session이 Route 기반 `/terminal-ws/`로 연결된다.
8. Ubuntu Docker compose 배포가 중지된다.
9. v0.0.9 변경분이 원격 브랜치에 push된다.

---

## 작업 메모

- 2026-05-11: v0.0.9 목표를 Ubuntu Docker 배포에서 OpenShift in-cluster 배포로 재정의했다.
- 2026-05-11: namespace는 대문자 불가 제약 때문에 `PBS-OCPOps` 대신 `pbs-ocpops`를 실제 이름으로 사용하기로 했다.
- 2026-05-11: Postgres/Qdrant는 우선 클러스터 내부에 같이 띄우고, 용량 문제가 생기면 외부 DB/Qdrant로 전환하기로 했다.
- 2026-05-11: 브라우저 Terminal WebSocket 기본 경로를 같은 origin의 `/terminal-ws/`로 변경하고 nginx proxy를 추가했다.
- 2026-05-11: OpenShift core/app/job manifest와 apply/cleanup script 초안을 작성했다.
- 2026-05-11: Studio 자주 묻는 질문에서 `What should I check first in ...?` 영어 fallback이 공식 문서 제목과 섞여 낮은 품질 질문을 만드는 문제를 확인했다.
- 2026-05-11: Postgres official metadata 기반 FAQ를 한국어 운영 질문 템플릿으로 교체해 문서 제목, 점검 대상, 명령/로그 확인 의도가 함께 들어가도록 수정했다.
- 2026-05-11: OCP 배포에서 Studio Chat 실운영 질문이 빠지는 원인이 `learning-seed-import` Job 누락임을 확인했다.
- 2026-05-11: `job-learning-seed.yaml`을 추가하고 apply script에서 KMSC guide를 `learning_paths`로 seed하도록 연결했다.
