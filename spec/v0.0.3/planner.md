# v0.0.3 - Remote SNO Terminal & Cluster Connection

## 목표

v0.0.3의 1순위 목표는 현재 로컬 CRC 기준으로 잡혀 있는 OpenShift 연결을 원격 서버 컴퓨터의 SNO(Single Node OpenShift) 클러스터로 전환하고, Studio의 Terminal Session과 cluster-aware UI가 같은 원격 클러스터 상태를 기준으로 동작하게 만드는 것이다.

대상 원격 서버:

- Remote host / SSH endpoint: `192.168.119.23`
- OpenShift API endpoint: `https://api.ocp.cywell.local:6443`
- Current API DNS resolution: `api.ocp.cywell.local -> 192.168.119.8`
- Current local config to replace: `OCP_API_BASE_URL=https://host.docker.internal:6443`

보안 전제:

- `OCP_API_TOKEN`, kubeconfig, pull secret, SSH key 같은 credential은 git에 커밋하지 않는다.
- `.env` 로컬 값 또는 배포 서버 secret/env 주입으로만 관리한다.
- Direct IP API 접속은 인증서 SAN mismatch 가능성이 높으므로 v0.0.3에서는 `OCP_INSECURE_SKIP_TLS_VERIFY=true`를 명시적으로 유지하되, 운영 전에는 cluster API DNS와 CA trust로 전환할 수 있게 둔다.

---

## 범위

### Core (P0 - v0.0.3 릴리스 기준)

- [x] 원격 SNO `192.168.119.23` 연결 방식 확정
- [x] `.env`/example/docs의 OCP 연결 값을 remote SNO 기준으로 정리
- [ ] Terminal Session auto-login이 remote SNO API에 성공하는지 검증
- [x] 앱 컨테이너에서 `api.ocp.cywell.local:6443` 네트워크 도달성 검증 경로 추가
- [x] Terminal Session UI에 연결 대상 cluster/server를 표시
- [x] `/tmp/playbookstudio-oc-login.log` 실패 원인을 API/Token/TLS/Network로 읽기 쉽게 노출
- [ ] Ops Console 또는 cluster status API가 remote SNO 상태를 기준으로 health를 표시
- [x] 원격 SNO 연결 smoke test 절차 문서화
- [x] frontend production build
- [x] backend focused tests

### P1 - 가능하면 포함

- [ ] `OCP_DEFAULT_NAMESPACE` 선택/표시 UX 추가
- [ ] cluster profile 개념 추가: `local-crc`, `remote-sno`
- [ ] Terminal Session reconnect 시 이전 cluster login 상태 표시
- [ ] `oc whoami`, `oc get clusterversion`, `oc get nodes` 결과를 학습 체크/cluster card에 연결
- [ ] WebSocket 연결 실패와 oc login 실패를 UI에서 분리 표시

### 비범위 (v0.0.4 이후)

- multi-user auth와 사용자별 kube credential vault
- 여러 클러스터 동시 접속
- SSH bastion 기반 remote shell execution
- OpenShift OAuth login flow 내장
- production-grade secret rotation

---

## 현재 구조 확인

현재 Terminal Session은 다음 경계로 구성되어 있다.

- Frontend: `apps/web/src/pages/workspace/TerminalSessionPanel.tsx`
  - 기본 WebSocket URL: 현재 host의 `ws://{hostname}:8770`
  - `VITE_TERMINAL_WS_URL`이 있으면 해당 값 우선
- Backend WebSocket: `src/play_book_studio/http/terminal_ws.py`
  - `TERMINAL_ENABLED=true`일 때 별도 WebSocket 서버를 띄우는 구조
  - `TERMINAL_HOST`, `TERMINAL_WS_PORT`, `TERMINAL_SHELL`, `TERMINAL_WORKDIR` 사용
- Shell wrapper: `deploy/scripts/terminal-entrypoint.sh`
  - `KUBECONFIG=/tmp/playbookstudio-kubeconfig`
  - `oc login --server="${OCP_API_BASE_URL}" --token="${OCP_API_TOKEN}"`
  - `OCP_INSECURE_SKIP_TLS_VERIFY=true`면 `--insecure-skip-tls-verify=true`
  - 실패 로그: `/tmp/playbookstudio-oc-login.log`
- Compose:
  - app service exposes `${TERMINAL_WS_PORT:-8770}:8770`
  - app service passes `.env` plus terminal env

따라서 v0.0.3은 새 terminal engine을 만들기보다, 현재 entrypoint/login/status 경계를 remote SNO에 맞게 강화하는 것이 우선이다.

---

## 구현 계획

### Step 1. Remote SNO 연결 정보 고정

필수 확인값:

```text
OCP_API_BASE_URL=https://api.ocp.cywell.local:6443
OCP_API_TOKEN=<remote-sno-token>
OCP_INSECURE_SKIP_TLS_VERIFY=true
OCP_DEFAULT_NAMESPACE=<optional>
TERMINAL_ENABLED=true
TERMINAL_WS_PORT=8770
TERMINAL_SHELL=/app/scripts/terminal-entrypoint.sh
```

검증 순서:

```bash
curl -k https://api.ocp.cywell.local:6443/version
oc login --server=https://api.ocp.cywell.local:6443 --token="$OCP_API_TOKEN" --insecure-skip-tls-verify=true
oc whoami
oc get clusterversion
oc get nodes -o wide
```

주의:

- `192.168.119.23`은 OpenShift API endpoint가 아니라 remote server SSH/IP로 확인됐다.
- API는 kubeconfig의 `server:` 값인 `https://api.ocp.cywell.local:6443`를 사용한다.
- 현재 Windows host와 app container 모두 `api.ocp.cywell.local -> 192.168.119.8`로 해석하고 `/version` 응답이 정상이다.
- 2026-05-09 host reachability check 결과 `192.168.119.23:22`는 열려 있지만 `:6443`, `:22623`, `:443`, `:80`은 닿지 않았다. 따라서 현재 IP는 remote server SSH endpoint로는 유효해 보이나, OpenShift API endpoint로는 아직 확정할 수 없다.

결정 분기:

```text
브라우저 Terminal Session -> PBS app WebSocket(:8770)
Terminal shell이 oc login -> OpenShift API(`https://api.ocp.cywell.local:6443`)
Terminal shell 자체를 remote server로 열기 -> SSH 192.168.119.23:22 + key/password 정책 필요
```

v0.0.3 P0는 먼저 `oc login` 대상 API endpoint를 확정한다. 만약 SNO API가 외부로 열려 있지 않고 SSH만 허용된다면, `terminal-entrypoint.sh`에서 바로 `oc login`하는 방식이 아니라 SSH tunnel 또는 remote SSH shell profile을 별도 설계해야 한다.

### Step 2. Environment/Compose 정리

목표:

- `.env.production.example` 또는 README에 remote SNO용 예시 추가
- `.env`의 로컬 CRC 값은 로컬 파일로만 유지하고 credential은 커밋하지 않는다
- `docker-compose.yml`은 현재처럼 `.env`를 app에 주입하되, remote SNO에 필요한 env 누락이 없는지 확인
- `OCP_INSECURE_SKIP_TLS_VERIFY`, `OCP_DEFAULT_NAMESPACE`가 app service에 전달되는지 검증

후보 변경:

- `.env.production.example`
- `README.md`
- `deploy/scripts/terminal-entrypoint.sh`
- 필요 시 `docker-compose.yml`

### Step 3. Terminal Login Diagnostics 개선

현재 실패 시 UI에는 "OpenShift CLI login failed" 정도만 보일 수 있다. v0.0.3에서는 원인 파악 시간을 줄인다.

개선 방향:

- `terminal-entrypoint.sh`에서 login 전 endpoint/token presence/network check 결과를 짧게 출력
- `/tmp/playbookstudio-oc-login.log`의 마지막 20줄을 실패 시 terminal에 보여주되 token은 절대 출력하지 않음
- 실패 유형을 구분:
  - network unreachable / timeout
  - TLS/certificate
  - unauthorized/token rejected
  - oc binary missing
  - API path/DNS mismatch

### Step 4. Terminal UI Cluster Target 표시

`TerminalSessionPanel.tsx` 또는 상위 Workspace panel에서 다음 정보를 표시한다.

- WebSocket 연결 상태: connected/error/closed
- shell label
- active cluster server: `https://api.ocp.cywell.local:6443`
- current identity: `oc whoami` 결과를 추후 API로 받을 수 있으면 표시

최소 구현은 ready event metadata에 cluster target을 포함하는 방식:

- `terminal_ws.py` ready payload에 `cluster_server` 추가
- `TerminalSessionPanel.tsx`의 `sessionMeta`에 `clusterServer` 추가

### Step 5. Cluster Status API와 Ops Console 연결 확인

현재 `OCP_API_BASE_URL`/`OCP_API_TOKEN` 설정은 backend settings에 이미 있다. v0.0.3에서는 Ops Console 쪽 API가 remote SNO를 보도록 확인한다.

확인 파일:

- `src/play_book_studio/http/ops_console_api.py`
- `src/play_book_studio/http/server_routes_ops.py`
- `apps/web/src/lib/opsConsoleApi.ts`

검증 대상:

```text
GET /api/ops/...
cluster version
nodes
operators
projects/namespaces
```

API가 mock/fallback을 쓰고 있으면 remote SNO live mode와 unavailable state를 명확히 분리한다.

### Step 6. Verification

Backend focused:

```powershell
python -m pytest tests/test_ops_console_api.py
python -m pytest tests/test_learning_api.py
```

Frontend:

```powershell
npm --prefix apps/web run build
```

Runtime smoke:

```powershell
docker compose up -d --build app web
docker compose ps app web
docker compose logs app --tail=80
```

Manual browser smoke:

```text
Workspace -> Terminal Session opens
Terminal prints OpenShift CLI login ready: https://api.ocp.cywell.local:6443
oc whoami returns expected user/service account
oc get nodes shows the SNO node
Ops Console live cluster status is connected
```

---

## 완료 기준 (DoD)

1. `feat/v0.0.3/remote-sno-terminal` 브랜치에서 remote SNO 연결 계획과 구현이 분리되어 추적된다.
2. 앱 컨테이너 내부 Terminal Session이 `https://api.ocp.cywell.local:6443` SNO API에 `oc login`할 수 있다.
3. Terminal UI가 WebSocket 연결 성공과 OpenShift login 성공/실패를 구분해 보여준다.
4. 실패 시 `/tmp/playbookstudio-oc-login.log`를 직접 찾지 않아도 원인 힌트를 UI/terminal 출력에서 볼 수 있다.
5. Ops Console cluster 연결 상태가 remote SNO 기준으로 표시된다.
6. credential은 git에 포함되지 않는다.
7. backend focused tests와 frontend build가 통과한다.
8. runtime smoke에서 `oc whoami`, `oc get clusterversion`, `oc get nodes`가 성공한다.

---

## 위험과 주의사항

- Direct IP `https://192.168.119.23:6443`가 아니라 kubeconfig의 API DNS `https://api.ocp.cywell.local:6443`를 사용해야 한다.
- SNO API가 DNS name만 허용되는 설치라면 Docker container에서 hosts/DNS 매핑이 필요하다.
- `OCP_API_TOKEN`은 만료될 수 있으므로 실패 원인을 token expiry와 network failure로 분리해야 한다.
- Terminal WebSocket 포트 `8770`이 방화벽/브라우저에서 접근 가능해야 한다.
- remote SNO가 사내망에 있고 Docker Desktop/WSL/network bridge 경로가 다르면 host에서는 되지만 app container에서는 안 될 수 있다.
- 실제 운영 배포 전에는 per-user credential isolation 없이 shared token을 쓰는 위험을 문서화해야 한다.

---

## 작업 메모

- 2026-05-09: v0.0.2 완료 브랜치 `feat/v0.0.2/metadata-ref-flow`를 `7f354b2`까지 push한 뒤 v0.0.3 브랜치 `feat/v0.0.3/remote-sno-terminal`을 생성했다.
- 2026-05-09: 원격 SNO 대상은 `192.168.119.23`으로 시작한다. 우선 가정 API는 `https://192.168.119.23:6443`이며, 실제 API DNS가 다르면 hosts/DNS 매핑을 추가한다.
- 2026-05-09: Terminal ready payload와 UI에 `cluster_server` 표시를 추가했다. `terminal-entrypoint.sh`는 `/version` reachability check, login failure classification, sanitized log tail 출력으로 강화했다. `.env.production.example`/README에 remote SNO env 예시를 추가했고, 당시 로컬 `.env`의 `OCP_API_BASE_URL`은 git 미추적 상태로 최초 후보 `https://192.168.119.23:6443`에 맞췄다. 검증: `npm --prefix apps/web run build`, `pytest tests/test_ops_console_api.py tests/test_learning_api.py -q`, `bash -n deploy/scripts/terminal-entrypoint.sh`.
- 2026-05-09: Host reachability: `Test-NetConnection 192.168.119.23 -Port 22` succeeded. `curl -k https://192.168.119.23:6443/version` failed with connection refused/unreachable, and ports `80`, `443`, `6443`, `22623` failed. Next concrete blocker is API endpoint/DNS/firewall confirmation, not frontend WebSocket wiring.
- 2026-05-09: User-provided kubeconfig confirms API endpoint `https://api.ocp.cywell.local:6443` with namespace `hcl-appscan-storage`. Host DNS resolves it to `192.168.119.8`; host and app container both successfully call `/version`. Local ignored `.env` was updated to `OCP_API_BASE_URL=https://api.ocp.cywell.local:6443`.
- 2026-05-09: App container was rebuilt/recreated with the new API URL and web was rebuilt. Container-level `/version` check succeeds. Direct `oc login --server="$OCP_API_BASE_URL" --token="$OCP_API_TOKEN" --insecure-skip-tls-verify=true` reaches the API but fails with `The token provided is invalid or expired.` Next blocker is refreshing local secret `OCP_API_TOKEN`, not API reachability.
