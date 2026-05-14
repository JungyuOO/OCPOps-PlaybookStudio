# v0.1.3 사용자별 학습 환경 자동 발급과 Live Cluster 통합


## 진행 메모 (2026-05-13)

- 2026-05-13: v0.1.3 planner 작성 시작. v0.1.2 완료(Phase D live smoke) 이후 다음 릴리즈로 잡되, Phase별 PR은 v0.1.2 마무리와 병행 가능한 범위에서 분리한다.
- 2026-05-13: 현재 터미널이 PBS 앱 Pod의 PTY에 직접 붙어 `ls` 시 `/app` 트리(`apps/`, `corpus/`, …)가 노출되어, 사용자가 `mkdir`/`vi`/`oc apply`를 자기 환경에서 실습할 수 없음을 확인. 사용자별 namespace + ServiceAccount + sandbox Pod 모델로 전환하기로 결정.
- 2026-05-13: 사용자 식별은 SMTP/회원가입/매직링크 미도입 결정. 기존 `pbs_session_owner` 쿠키(HttpOnly, SameSite=Lax, max-age=365일) 기반 `owner_hash` 32자(sha256)를 그대로 사용. 브라우저-바운드 정체성의 한계는 1회성 UI 안내로 명시.
- 2026-05-13: `WorkspacePage`의 Live Cluster 토글이 동작하지 않는 원인 파악. (1) `clusterConnectionStatus`(OCP 프로파일 ping)는 'connected'이지만 터미널 WS는 "Session exited" 상태 → 두 상태 미동기화, (2) `requestPayload`에 `mode: 'ops'`가 하드코딩되어 있고 `currentMode === 'live_cluster'` 분기 자체가 없음. 백엔드 라이브 cluster chat은 `src/play_book_studio/http/ops_console_api.py`의 `/api/v1/chat/query/stream`로 이미 완성되어 있고 `OpsConsolePage`만 사용 중. 즉 "백엔드가 없다"가 아니라 "Workspace가 기존 ops 백엔드를 호출하지 않는 상태"임을 확정.

---

## 목표

v0.1.0이 RAG 파이프라인/의도/스트리밍, v0.1.1이 추천 질문 톤, v0.1.2가 청크 품질 재구축을 다뤘다면 **v0.1.3은 "사용자가 실제로 자기 OCP 환경에서 실습하고, 그 환경을 PBS가 분석할 수 있게 만드는" 릴리즈다.**

현재 터미널은 PBS 앱 Pod의 PTY에 붙어 있어 사용자가 `ls`를 치면 PBS 앱의 소스 트리가 나온다. 학습자가 `mkdir`/`vi`/`oc apply -f`로 실습할 수 없고, PBS의 "Live Cluster" 답변은 `_ops_live_context`까지 다 만들어진 백엔드를 호출하지 않아 사실상 동작하지 않는다.

v0.1.3은 다음 두 축을 합친다.

1. **사용자별 학습 환경 자동 발급**: 첫 접속 시 backend가 `pbs-user-<owner_hash[:8]>` namespace + `learner` ServiceAccount + `home-learner` PVC + `sandbox` Deployment를 생성한다. 사용자는 ID/PW를 입력하지 않고, 터미널이 자기 sandbox Pod에 자동 연결된다. 일정 시간 idle 시 Pod replicas=0(동면), 14일 미사용 + `pinned=false`면 namespace 통째 삭제.
2. **Live Cluster 모드 정상화**: 워크스페이스 Live 토글이 (a) 터미널 WS 상태와 동기화되어 끊긴 상태에서는 disable되고, (b) 켜졌을 때 `sendOpsChatStream('/api/v1/chat/query/stream', { connection_id, namespace })`로 라우팅되며, (c) 최근 터미널 명령/결과가 분석 컨텍스트에 attach된다. 토글 UI는 채팅 화면 좌측 상단의 Docs/Live 형태로 이동한다.

회원가입/이메일 인증/외부 OAuth는 v0.1.3 비범위로 유지하며, 필요해지는 시점에 `resolve_session_owner` 헤더 1순위 자리에 추가하는 점진적 확장 경로만 열어둔다.

---

## 원칙

- 사용자에게 ID/PW/이메일/회원가입 요구하지 않는다. 기존 `owner_hash` 쿠키(브라우저 1년 유지)를 그대로 학습 환경의 주인 키로 사용한다.
- 사용자별 격리는 namespace + ServiceAccount + PVC + Pod 단위로 한다. SSH/OS 사용자 격리는 도입하지 않는다.
- 사용자 sandbox Pod 안에서는 자기 namespace의 RBAC `edit`만 허용한다. 다른 사용자 namespace의 리소스 list/get은 403으로 자동 차단된다.
- 클러스터 어드민 토큰은 backend가 보유하는 broker ServiceAccount로만 사용하고, 사용자 화면/Pod에는 절대 노출하지 않는다.
- 학습 환경이 1년간 같은 브라우저에 묶이는 한계는 1회성 UI 안내로만 명시한다. 이메일/SMTP 인프라는 도입하지 않는다.
- 리소스 청소는 hibernate(30분 idle → Pod replicas=0)와 namespace TTL(14일 미사용 → 통째 삭제)의 2단으로 한다. namespace TTL은 사용자가 "보관" 토글로 잠글 수 있다.
- `WorkspacePage`의 Live Cluster 토글은 백엔드 `ops_console_api`(이미 존재)와 연결하며, 라이브 cluster chat 로직을 새로 작성하지 않는다.
- 터미널 WS 상태(`closed`/`error`)는 부모 페이지로 콜백되어 토글 disable·badge 표시에 사용된다.
- 모든 신규 자원은 라벨 `pbs.session=true`, `pbs.owner-hash=<hash>`, `pbs.created-at`, `pbs.last-active-at`, `pbs.pinned`을 일관되게 부착한다.

---

## 범위

### Core (P0 - v0.1.3 릴리스 기준)

- [x] v0.1.3 브랜치 생성 및 planner 작성
- [x] backend broker ServiceAccount(`pbs-ocpops:terminal-broker`) + ClusterRole/RoleBinding 정의
- [x] `cluster/workspace_provisioner.py` 신규: `ensure_user_workspace(owner_hash)` / `hibernate_user_workspace` / `wake_user_workspace` / `delete_user_workspace`
- [x] namespace `pbs-user-<owner_hash[:8]>` 자동 생성 + 라벨 부착
- [x] ServiceAccount `learner` + RoleBinding `edit` 자동 생성
- [x] PVC `home-learner`(1Gi, RWO) 자동 생성, sandbox Pod `/home/learner`에 mount
- [x] Deployment `sandbox` 자동 생성 (이미지: oc CLI + vi + bash 포함한 ubi9 파생)
- [x] terminal WS 진입부 변경: 기존 앱 Pod PTY 대신 `oc exec` 통해 사용자 sandbox Pod로 연결
- [x] 부트스트랩 진행 단계 progress 프레임을 WS로 송신(준비중 UI 표시)
- [ ] 사용자 첫 접속 1회용 안내 메시지(브라우저-바운드 정체성, 14일 TTL 설명)
- [x] in-cluster CronJob: 30분 idle → Pod replicas=0(동면), 14일 미사용 + `pinned=false` → namespace 삭제
- [ ] `last-active-at` 라벨 갱신(WS 메시지 시 60초당 1회 patch)
- [ ] "보관하기" 토글(`pbs.pinned=true/false` 패치) UI + API
- [ ] "환경 초기화" 버튼: 현재 owner_hash의 namespace 삭제 후 다음 접속 시 신규 발급
- [x] `TerminalSessionPanel`에 `onSessionStateChange(state)` prop 추가, WorkspacePage가 `terminalConnected` state 보유
- [x] Live Cluster 토글 disable 조건: `!terminalConnected` (현재의 `!isClusterConnected`와 AND)
- [x] Live Cluster 토글을 채팅 화면 좌측 상단 `Docs / Live` 토글 UI로 이동
- [x] `currentMode === 'live_cluster'`일 때 `sendOpsChatStream('/api/v1/chat/query/stream', ...)`로 분기
- [x] Live 응답(`OpsChatResponse` → 기존 메시지 형) 변환 어댑터
- [x] 최근 터미널 명령/결과를 Live chat payload에 attach (`recent_terminal_actions`)
- [x] Live chat의 `namespace`는 자동 발급된 `pbs-user-<owner_hash[:8]>`로 라우팅
- [x] backend `_chat_payload`가 `recent_terminal_actions`를 받아 cluster context와 함께 의도 분류/근거로 사용
- [x] ResourceQuota 자동 부착(per-user ns: cpu 500m, mem 1Gi, pods 5, pvc 2)
- [x] NetworkPolicy 자동 부착(per-user ns: 같은 ns 내부 + cluster API + 학습용 mirror registry만)
- [ ] backend 동시 활성 workspace 상한 env(`PBS_MAX_ACTIVE_WORKSPACES`) + 초과 시 친절한 안내
- [ ] backend focused tests 통과
- [ ] frontend production build 통과
- [ ] Playwright smoke: 첫 접속 부트스트랩, `mkdir`/`vi` 실습, Live Cluster 토글 OFF/ON 분기, 동면 후 재접속

### Extras (P1 - 가능하면 포함)

- [ ] sandbox Pod warm pool(예: idle 0개 유지, 부트스트랩 latency 단축)
- [ ] 사용자별 작업 히스토리 viewer: 명령 로그를 `/home/learner/.pbs/history.log`로 별도 보존
- [ ] "내 namespace 자원 한눈에" 좌측 패널: 자기 ns의 Pod/Service/Deployment를 표 뷰로 표시
- [ ] `recent_terminal_actions` 길이/요약 정책 LLM 압축
- [ ] sandbox 이미지 multi-arch 빌드(amd64/arm64)
- [ ] 보관(pinned) 사용자에게 14일 만료 임박 알림 배너
- [ ] terminal 명령 결과 일부를 chat citation으로 직접 인용
- [ ] WorkspacePage가 사용자 namespace의 ResourceQuota 사용량을 헤더에 표시

### 비범위 (v0.1.4 이후)

- 이메일 발송(매직링크, 알림, 만료 통지) 인프라
- 외부 OAuth(Google/GitHub/Kakao) 연동
- 사내 LDAP/AD/OIDC 위임
- OCP htpasswd IDP 자동 사용자 등록
- 회원가입 화면, 비밀번호 정책
- 사용자별 PVC 백업/스냅샷/다른 ns로 이전
- 다중 sandbox Pod(개발 + 운영 분리 등)
- 사용자 그룹/팀/조직 개념
- 결제/quota 등급/엔터프라이즈 권한 모델
- Cross-cluster 학습 환경(현재는 단일 SNO 가정)

---

## 단계 그룹화 (Phase 분리)

v0.1.3은 인프라 변경(클러스터 자원 발급)과 UX 변경(토글 통합)이 함께 들어간다. 두 축의 위험도가 달라서 4개 phase로 나눈다.

| Phase | PR | 내용 | 클러스터 변경 | 사용자 가시성 | 평가 기준 |
|---|---|---|---|---|---|
| **A** | PR #1 | terminal 상태 콜백 + Live 토글 disable 조건 강화 + 토글 UI 좌상단 이동(Docs/Live) | X | 끊긴 상태에서 토글 불가, 위치 명확 | 회귀 없음, Playwright smoke |
| **B** | PR #2 | Workspace Live 모드를 기존 `ops_console_api`로 라우팅 + `OpsChatResponse` 어댑터 + 최근 터미널 명령 attach | X | Live 토글 ON에서 실제 cluster 컨텍스트 답변 | smoke: "내 cluster의 Pod 알려줘"에서 라이브 인용 발생 |
| **C** | PR #3 | broker SA + `workspace_provisioner` + ensure/hibernate/wake/delete + terminal WS가 사용자 sandbox Pod로 exec | O (RBAC + image) | `ls` 결과가 `/home/learner`, `mkdir`/`vi` 정상 동작 | 첫 접속 부트스트랩 ≤ 20s, 격리 검증(다른 ns 403) |
| **D** | PR #4 | CronJob 동면/삭제 + `pbs.last-active-at` 갱신 + 보관/초기화 토글 + 사용자 namespace를 Live chat에 연결 | O (CronJob) | 동면-재개-만료 라이프사이클 동작, "내 cluster"가 진짜 사용자 ns 기준 | 7일/14일 시뮬레이션, 보관 시 잠금 |

원칙:

- **Phase A·B는 클러스터 변경 없이 가능**하므로 v0.1.2 마무리(Phase D live smoke)와 병행 진행 가능하다. 사용자가 체감하는 가장 큰 결함("Live 누르면 답이 없다")이 B에서 즉시 해소된다.
- **Phase C는 한 번에 묶음**. namespace/SA/PVC/Deployment/RoleBinding 중 일부만 배포되면 격리가 깨진다. dev SNO에 dry-run으로 검증한 뒤 merge.
- **Phase D**는 라이프사이클 정책이라 단독으로 묶는다. 만료 시뮬레이션은 라벨 시간을 인위적으로 과거로 patch해서 테스트.
- v0.1.3 릴리즈는 Phase D 완료 + smoke 통과 시점. A·B·C 각각 단독으로는 v0.1.3 릴리즈로 간주하지 않는다.

---

## 배경: 현재 상태 분석

### 1. 터미널이 PBS 앱 Pod의 PTY에 붙어 있다

- `apps/web/src/pages/workspace/TerminalSessionPanel.tsx`가 backend WS로 PTY 연결
- backend는 현재 앱 컨테이너 안에서 `/bin/bash`를 spawn → `ls` 결과가 PBS 앱 트리(README.md, apps, corpus, db, scripts, src, …)
- 사용자가 `mkdir test`/`vi sample.yaml`/`oc apply -f sample.yaml`을 해도 그건 PBS 앱 컨테이너에서 일어남. 다른 사용자도 같은 결과를 본다(격리 0).

### 2. 사용자 식별은 이미 owner_hash로 분리되어 있다

- `src/play_book_studio/http/session_owner.py`:
  - 1순위 헤더: `X-Forwarded-User`/`X-Remote-User`/`X-User` (현재 미사용 — 미래 SSO용 슬롯)
  - 2순위 쿠키: `pbs_session_owner` (HttpOnly, SameSite=Lax, max-age=365일)
  - 3순위: 새 UUID 생성 후 Set-Cookie
- raw owner → sha256 32자 = `owner_hash`
- `SessionStore.for_owner(owner_hash)`로 채팅 세션·파일·DB 행이 이미 사용자별로 scope됨

→ "이메일 없는 사용자별 식별"은 이미 완성. 클러스터 자원만 이 키로 발급하면 됨.

### 3. 라이브 cluster chat 백엔드는 이미 완성되어 있고 워크스페이스만 안 쓴다

`src/play_book_studio/http/ops_console_api.py` (3,510줄):

```
POST /api/v1/chat/query          (line 3233)
POST /api/v1/chat/query/stream   (line 3242)  ← NDJSON 스트리밍

핵심 함수:
  _ops_live_context              line 1793  cluster + namespace 기준 inventory 수집
  _classify_ops_chat_intent      line 1127
  _namespace_health_chat_response   line 1208
  _deployment_troubleshooting_chat_response   line 1297
  _route_service_chat_response   line 1368
  _selected_live_resource_details   line 1963
  _resource_names_by_type        line 1831
  _classify_ops_artifact_intent     line 1860
```

프런트 라이브러리도 있음 — `apps/web/src/lib/opsConsoleApi.ts`:

```
sendOpsChat({ message, connection_id, namespace, history })          line 574
sendOpsChatStream(payload, onEvent)                                  line 586
  → /api/v1/chat/query/stream
```

호출처: `apps/web/src/pages/OpsConsolePage.tsx:1347`. **WorkspacePage는 호출 안 함.**

### 4. WorkspacePage Live Cluster 토글의 두 버그

**버그 A — 터미널 끊겨도 토글 활성 유지**

```
WorkspacePage.tsx:1323  isClusterConnected = clusterConnectionStatus === 'connected'
WorkspacePage.tsx:1324  clusterConnectionStatus는 normalizeClusterConnectionStatus(connection)
                         (OCP 프로파일 status 기반: 'ready'/'active' 등)

vs.

TerminalSessionPanel.tsx:269-273  WS에서 'exit' 페이로드 받으면 internal state='closed'
                                  하지만 부모(WorkspacePage)에 통지하지 않음
```

→ 터미널 WS가 죽어도 `isClusterConnected`는 true. 토글이 계속 클릭 가능.

**버그 B — Live 모드가 chat 페이로드에 반영되지 않음**

```
WorkspacePage.tsx:3018-3034  requestPayload = {
                                query, sessionId,
                                mode: 'ops',  ← 하드코딩
                                ...
                              }
WorkspacePage.tsx:3098       sendChatStream(requestPayload)
                              → /api/chat/stream  (Document RAG 경로)
```

grep 결과 `currentMode === 'live_cluster'` 참조 위치는 4군데 모두 UI className/aria/disabled. **chat 송신부 분기 없음.**

### 5. 자동 청소 정책 없음

- 사용자가 만든 리소스는 현재 앱 Pod 안에서 일어나거나 cluster admin 권한으로 만들어진 default ns에 쌓임
- 청소 CronJob 없음
- v0.1.3에서 사용자별 namespace로 격리되면 이 부분도 정책이 필요

---

## 아키텍처 방향

### 1. 사용자 식별 → 클러스터 자원 매핑

```
브라우저 ──────► PBS backend
  pbs_session_owner=<uuid>            ▼
                              resolve_session_owner
                                     │
                                     ▼
                              owner_hash (sha256 32자)
                                     │
                                     ▼
                       short_hash = owner_hash[:8]   (충돌 무시 수준)
                                     │
        ┌───────────────────────────┴──────────────────────────┐
        ▼                            ▼                          ▼
  namespace                    ServiceAccount               PVC + Deployment
  pbs-user-<short_hash>        learner                      home-learner / sandbox
```

### 2. 자원 라벨 규약

모든 사용자별 자원에 동일 라벨:
```
pbs.session         = true
pbs.owner-hash      = <full 32자 hash>
pbs.short-hash      = <8자>
pbs.created-at      = <RFC3339>
pbs.last-active-at  = <RFC3339>   # backend가 60s 주기로 갱신
pbs.hibernated      = false       # CronJob이 갱신
pbs.pinned          = false       # 사용자 보관 토글
```

### 3. backend broker ServiceAccount

```
namespace: pbs-system
ServiceAccount: terminal-broker
ClusterRole: pbs-terminal-broker
  - namespaces: create, get, patch, delete
  - serviceaccounts, rolebindings, persistentvolumeclaims, deployments, pods, pods/exec, pods/log
  - resourcequotas, networkpolicies (사용자 ns 안에서만)
ClusterRoleBinding: pbs-terminal-broker
```

PBS backend Pod의 SA를 이 broker SA로 운영하고, `admin/admin123` 등 cluster-admin 사용은 즉시 폐기.

### 4. sandbox 이미지

```
base: registry.access.redhat.com/ubi9/ubi-minimal
+ oc CLI (matching cluster version)
+ kubectl
+ vi/nano
+ bash, less, grep, jq
+ curl
+ /etc/skel/.bashrc (PS1, PROMPT_COMMAND, aliases)
WORKDIR: /home/learner
USER: 1001 (non-root)
```

### 5. 부트스트랩 시퀀스

```
사용자가 터미널 패널 열기
    │
    ▼ WS 핸드셰이크: backend가 owner_hash 결정
    ▼
ensure_user_workspace(owner_hash):
    [check] namespace pbs-user-<h>           [create if absent]
    [check] ResourceQuota pbs-user-quota     [create if absent]
    [check] NetworkPolicy pbs-user-isolation [create if absent]
    [check] ServiceAccount learner           [create if absent]
    [check] RoleBinding learner-edit          [create if absent]
    [check] PVC home-learner                  [create if absent]
    [check] Deployment sandbox (replicas==1)  [create or scale-up if 0]
    [wait]  Pod Ready (timeout ~20s)
    │
    ▼ backend가 SA learner의 단명 토큰 발급 → Pod의 /root/.kube/config에 주입
    ▼
oc exec -it -n pbs-user-<h> <sandbox-pod-name> -- /bin/bash
    │
    ▼ PTY 스트림 시작, 첫 줄에:
"학습 네임스페이스 pbs-user-<h>에 연결되었습니다."
"oc whoami → system:serviceaccount:pbs-user-<h>:learner"
```

부트스트랩 진행 단계는 WS progress 프레임으로 사용자에게 표시:
```
{type: 'bootstrap_stage', stage: 'namespace_ready'}
{type: 'bootstrap_stage', stage: 'sandbox_ready'}
{type: 'ready', shell: '/bin/bash', workdir: '/home/learner', ...}
```

### 6. 동면(Hibernate) + TTL

```
T0                    첫 접속 → ensure
T0 + 매 60s WS msg    pbs.last-active-at patch
T0 + 30분 idle        CronJob: scale deployment/sandbox replicas=0
                      pbs.hibernated=true. PVC/SA/RoleBinding/ns 유지
재접속                 ensure가 replicas=1로 wake. 동일 PVC 마운트 → 어제 파일 그대로
T0 + 14일 미사용       CronJob: oc delete namespace pbs-user-<h>
                      (단, pbs.pinned=true면 카운터 정지)
```

CronJob 구현:
```
namespace: pbs-system
CronJob name: workspace-reaper
schedule: */15 * * * *
job container image: oc CLI
script:
  now=$(date -u +%s)
  oc get ns -l pbs.session=true -o json |
    jq -r '.items[] | [.metadata.name, .metadata.labels."pbs.last-active-at", .metadata.labels."pbs.pinned"] | @tsv' |
    while read ns last pinned; do
      idle_seconds=$(( now - $(date -u -d "$last" +%s) ))
      if [ "$pinned" = "true" ]; then continue; fi
      if [ $idle_seconds -gt $((14*86400)) ]; then
        oc delete ns "$ns"
      elif [ $idle_seconds -gt $((30*60)) ]; then
        oc scale deployment/sandbox -n "$ns" --replicas=0 --ignore-not-found
        oc label ns "$ns" pbs.hibernated=true --overwrite
      fi
    done
```

### 7. Live Cluster chat 라우팅

```
WorkspacePage.tsx 채팅 송신부:

if (currentMode === 'live_cluster' && terminalConnected) {
  await sendOpsChatStream(
    {
      message: trimmed,
      connection_id: activeFooterConnection?.connection_id ?? '',
      namespace: userWorkspaceNamespace,   // pbs-user-<h>
      history: lastNMessages,
      recent_terminal_actions: lastTerminalActions,
    },
    onEvent  // OpsChatStreamEvent → 기존 message 형 어댑터
  );
} else {
  await sendChatStream(requestPayload, ...);
}
```

backend `_chat_payload`(ops_console_api.py)는 이미 `connection_id`, `namespace`, `history`를 받아 `_ops_live_context`로 cluster inventory 수집 → intent 분류 → 답변. v0.1.3에서는 여기에 `recent_terminal_actions` 필드만 추가로 받아 cluster context 옆에 보조 근거로 끼워넣는다.

### 8. 최근 터미널 명령/결과 attach

```
TerminalSessionPanel에서 이미 detectClusterSignal(command)이 명령 패턴 매칭 중.
WorkspacePage가 다음 ring buffer 보유:
  recentTerminalActions: Array<{
    command: string;
    outputExcerpt: string;     // stdout 최근 1KB 잘라서
    exitCode: number | null;
    timestamp: string;
    namespace: string;
  }>
  최대 N개(예: 5). LRU.
Live chat 전송 시 payload.recent_terminal_actions로 포함.
```

backend는 이 배열을 LLM 컨텍스트에 다음 형식으로 포함:
```
[Terminal Action]
$ oc get pods -n pbs-user-a3f9
NAME              READY   STATUS
my-app-7c..-xyz   1/1     Running
exit_code: 0
```

### 9. 토글 UI 좌상단 이동

```
현재 위치: WorkspacePage.tsx:4352-4381 (chat-input-wrapper 안)
신규 위치: 채팅 메시지 영역 좌상단 (.chat-message-stream 위)
형태:
  ┌─────────────────────────┐
  │ [● Docs] [○ Live]       │  ← 좌측 정렬, 작은 토글
  │                         │
  │  (대화 메시지들)         │
  │                         │
  └─────────────────────────┘
- disabled={!terminalConnected || (live이지만 cluster 연결 없음)}
- title 속성으로 disable 사유 안내
```

### 10. 첫 접속 1회용 안내

`/home/learner` PVC가 비어 있을 때(즉 첫 부트스트랩) 다음 안내를 chat에 system 메시지로 1회 표시:
```
환영합니다. 이 학습 환경은 현재 브라우저에 1년간 연결됩니다.
다른 브라우저, 시크릿 창, 쿠키 삭제 시에는 새 환경이 만들어집니다.
환경을 14일 동안 사용하지 않으면 자동으로 정리됩니다.
보존이 필요하면 우측 상단의 "보관하기"를 켜 주세요.

학습 네임스페이스: pbs-user-<h>
```

---

## 구현 계획

### Step 1. v0.1.3 작업 기준 확정

- `feat/v0.1.3/user-workspace-bootstrap` 브랜치 생성
- `spec/v0.1.3/planner.md` 작성 (이 문서)
- UTF-8 유지, 작업 메모를 planner에 누적

### Step 2. terminal 상태 콜백 (Phase A)

수정 파일:
```
apps/web/src/pages/workspace/TerminalSessionPanel.tsx
  - props에 onSessionStateChange?: (state: 'connecting'|'connected'|'closed'|'error') => void
  - 내부 setState 호출 위치마다 props 콜백 호출
apps/web/src/pages/WorkspacePage.tsx
  - terminalConnected: boolean state 추가
  - <TerminalSessionPanel onSessionStateChange={(s) => setTerminalConnected(s === 'connected')} />
  - useEffect 1377-1381의 의존성을 terminalConnected로 변경(또는 AND 결합)
```

테스트: `tests/test_terminal_session_state_sync.spec.tsx` 또는 Playwright smoke.

### Step 3. Live 토글 UI 좌상단 이동 (Phase A)

수정 파일:
```
apps/web/src/pages/WorkspacePage.tsx
  - chat-mode-switch 마크업을 chat 메시지 영역 좌상단으로 이동
  - "Document Learning"/"Live Cluster" 라벨을 "Docs"/"Live"로 축약
apps/web/src/pages/WorkspacePage.css
  - .chat-mode-switch 좌상단 배치 CSS
  - disabled 시각 표시 강화
```

조건:
- `disabled={!terminalConnected}` 강제
- `title`로 disable 사유 명시("터미널이 연결되어야 Live 모드를 사용할 수 있습니다")

### Step 4. Live chat 라우팅 (Phase B)

수정 파일:
```
apps/web/src/pages/WorkspacePage.tsx
  - import { sendOpsChatStream, OpsChatStreamEvent, OpsChatResponse } from '../lib/opsConsoleApi'
  - chat 송신부(3018~3119 근처)에 분기 추가:
      if (currentMode === 'live_cluster' && terminalConnected) {
        await sendOpsChatStream({ message, connection_id, namespace, history, recent_terminal_actions }, onEvent)
      } else {
        await sendChatStream(requestPayload, ...)
      }
  - OpsChatResponse → 기존 ChatMessage 형 변환 어댑터 헬퍼 추가
apps/web/src/lib/opsConsoleApi.ts
  - sendOpsChatStream payload에 recent_terminal_actions? 필드 추가(선택)
```

backend:
```
src/play_book_studio/http/ops_console_api.py
  - _chat_payload 입력에 recent_terminal_actions를 받아 _ops_live_context와 함께 LLM 컨텍스트에 포함
  - 답변 출처 라벨에 "Live Cluster"/"Terminal Action" 구분 표시
```

테스트: `tests/test_ops_chat_recent_terminal_actions.py`, `tests/test_workspace_live_routing.spec.tsx`.

### Step 5. terminal 명령/결과 ring buffer (Phase B)

수정 파일:
```
apps/web/src/pages/WorkspacePage.tsx
  - recentTerminalActions: state(Array, max 5)
  - <TerminalSessionPanel onCommandSubmitted={...} onOutputChunk={...} />로 갱신
apps/web/src/pages/workspace/TerminalSessionPanel.tsx
  - onCommandSubmitted prop은 이미 존재(line 304 의존성). onOutputChunk(stdout 일부) 신규 추가
```

테스트: `tests/test_recent_terminal_actions_ring.spec.tsx`.

### Step 6. backend broker SA + RBAC (Phase C)

신규 파일:
```
deploy/openshift/broker-rbac.yaml
  - ServiceAccount pbs-system:terminal-broker
  - ClusterRole pbs-terminal-broker
  - ClusterRoleBinding
src/play_book_studio/cluster/__init__.py
src/play_book_studio/cluster/k8s_client.py
  - broker SA 토큰 in-cluster mount(/var/run/secrets/kubernetes.io/serviceaccount/token) 사용
  - kubernetes python client 초기화 헬퍼
```

배포 변경:
```
deploy/openshift/app.yaml
  - app Deployment의 serviceAccountName을 broker SA로 변경
  - admin/admin123 사용 제거
```

테스트: `tests/test_broker_rbac_smoke.py`(클러스터 없이 manifest schema 검증).

### Step 7. workspace_provisioner 모듈 (Phase C)

신규 파일:
```
src/play_book_studio/cluster/workspace_models.py
  @dataclass WorkspaceHandle:
      namespace: str
      pod_name: str
      sa_name: str
      ready: bool
      created: bool      # 새로 만든 경우 True
      hibernated: bool
src/play_book_studio/cluster/workspace_provisioner.py
  ensure_user_workspace(owner_hash) -> WorkspaceHandle
  hibernate_user_workspace(owner_hash) -> None
  wake_user_workspace(owner_hash) -> WorkspaceHandle
  delete_user_workspace(owner_hash) -> bool
  touch_last_active(owner_hash) -> None    # 라벨 patch
  set_pinned(owner_hash, pinned: bool) -> None
```

테스트: `tests/test_workspace_provisioner_unit.py`(k8s API mock), `tests/test_workspace_provisioner_smoke.py`(dev SNO 통합).

### Step 8. sandbox 이미지 빌드 (Phase C)

신규 파일:
```
deploy/sandbox/Dockerfile
  FROM registry.access.redhat.com/ubi9/ubi-minimal
  RUN microdnf install -y bash vim less grep jq curl
  COPY oc /usr/local/bin/oc
  COPY kubectl /usr/local/bin/kubectl
  COPY skel/ /etc/skel/
  USER 1001
  WORKDIR /home/learner
.github/workflows/publish-images.yml
  - sandbox 이미지 빌드/푸시 job 추가 (ghcr.io/.../pbs-sandbox:v0.1.3)
```

### Step 9. terminal WS를 사용자 sandbox로 라우팅 (Phase C)

수정 파일:
```
src/play_book_studio/http/terminal_ws.py
  - 기존 in-app PTY spawn 코드 제거
  - 핸드셰이크 직후 ensure_user_workspace(owner_hash) 호출
  - 진행 단계 progress 프레임 송신
  - k8s_client.connect_pod_exec(namespace, pod, '/bin/bash', tty=True)로 SPDY/WS 스트림 받고 client WS와 bridge
src/play_book_studio/http/terminal_session.py
  - learning context 전달 시 새 namespace/Pod 정보 함께 흘리도록 갱신
```

테스트: `tests/test_terminal_ws_pod_exec.py`(unit, k8s mock).

### Step 10. ResourceQuota/NetworkPolicy 자동 부착 (Phase C)

`workspace_provisioner.ensure_user_workspace` 안에서 namespace 생성 직후:
```
ResourceQuota pbs-user-quota:
  hard:
    cpu: 500m, memory: 1Gi
    pods: 5
    persistentvolumeclaims: 2
    requests.storage: 2Gi

NetworkPolicy pbs-user-isolation:
  podSelector: {}
  policyTypes: [Ingress, Egress]
  ingress: [{from: [{podSelector: {}}]}]    # 같은 ns 내부만
  egress:
    - to:
        - namespaceSelector: { matchLabels: { name: openshift-kube-apiserver } }
        - namespaceSelector: { matchLabels: { name: openshift-dns } }
      ports: [...]
    - to: [{ ipBlock: { cidr: <mirror_registry_cidr> } }]
```

### Step 11. CronJob 동면/삭제 (Phase D)

신규 파일:
```
deploy/openshift/workspace-reaper-cronjob.yaml
  - schedule: "*/15 * * * *"
  - serviceAccountName: terminal-broker
  - container: oc CLI 이미지 + reaper 스크립트
deploy/openshift/scripts/workspace-reaper.sh
  - 위 아키텍처 6의 스크립트
```

테스트: `tests/test_workspace_reaper_script.py`(시간 라벨 시뮬레이션).

### Step 12. last-active-at 갱신 + 보관/초기화 토글 (Phase D)

수정 파일:
```
src/play_book_studio/http/terminal_ws.py
  - WS 메시지 수신 시 60s rate-limit된 touch_last_active(owner_hash) 비동기 호출
src/play_book_studio/http/server_routes_ops.py 또는 신규 workspace_admin_api.py
  - POST /api/v1/workspace/pin       body: { pinned: bool }
  - POST /api/v1/workspace/reset     (delete + ensure)
  - GET  /api/v1/workspace/status    (namespace, hibernated, last_active_at, expires_at)
apps/web/src/lib/runtimeApi.ts
  - setWorkspacePinned, resetWorkspace, getWorkspaceStatus
apps/web/src/pages/WorkspacePage.tsx
  - 좌상단 또는 헤더에 상태 배지 + "보관하기"/"환경 초기화" 버튼
```

테스트: `tests/test_workspace_admin_api.py`.

### Step 13. Live chat의 namespace를 사용자 workspace로 연결 (Phase D)

수정 파일:
```
apps/web/src/pages/WorkspacePage.tsx
  - userWorkspaceNamespace state(부트스트랩 시 backend에서 받음)
  - sendOpsChatStream payload의 namespace를 이 값으로 강제
src/play_book_studio/http/ops_console_api.py
  - _chat_payload가 namespace가 사용자 ns이면 _ops_live_context도 사용자 ns 한정 inventory만 수집하도록 가드
  - 다른 ns 질의가 들어오면 403 안내 답변
```

### Step 14. 첫 접속 안내 메시지 (Phase C/D 사이)

수정 파일:
```
src/play_book_studio/cluster/workspace_provisioner.py
  - ensure 후 created=True면 backend가 사용자 chat history에 system 메시지 1회 prepend
apps/web/src/pages/WorkspacePage.tsx
  - system 메시지 종류 추가, 첫 번째 turn으로 표시
```

### Step 15. 회귀/통합 테스트

```
backend focused:
  pytest tests/test_workspace_provisioner_unit.py
  pytest tests/test_ops_chat_recent_terminal_actions.py
  pytest tests/test_workspace_admin_api.py
  pytest tests/test_workspace_reaper_script.py
  pytest tests/test_terminal_ws_pod_exec.py

frontend:
  npm --prefix apps/web run build

Playwright (dev SNO):
  - 첫 접속 부트스트랩 → "학습 네임스페이스 ... 연결" 메시지
  - mkdir test/touch a.yaml/vi a.yaml/oc apply -f a.yaml → 자기 ns에 생성됨
  - 다른 ns 자원 list 403
  - 터미널 종료 → Live 토글 disable
  - Live ON, "현재 내 cluster의 Pod 알려줘" → 자기 ns 인용
  - 동면 시뮬레이션 → 재접속 시 동일 PVC, 어제 파일 복원
  - 14일 미사용 시뮬레이션 → ns 삭제 확인
```

### Step 16. OCP 재배포

```
1. dev SNO에 broker-rbac, sandbox image, app Deployment serviceAccountName, CronJob 적용
2. oc rollout restart deployment/app deployment/web -n pbs-ocpops
3. Playwright smoke 전체 재실행
4. live smoke: 6개 v012 beginner 케이스 + 6개 v013 신규 케이스
```

신규 v013 smoke 케이스(예시):
```
v013-001 첫 접속자 부트스트랩 시간 ≤ 20s
v013-002 mkdir/vi/oc apply -f 정상 동작
v013-003 다른 사용자 ns 자원 403 확인
v013-004 Live ON에서 "내 cluster의 Pod" 응답에 자기 ns 인용
v013-005 동면 후 재접속 시 어제 파일 보존
v013-006 보관하기 ON 시 만료 카운터 정지
```

---

## API 확인 목록

| API | 목적 | v0.1.3 상태 |
|---|---|---|
| `/api/chat`, `/api/chat/stream` | Document RAG | 유지 |
| `/api/v1/chat/query`, `/api/v1/chat/query/stream` | Live cluster RAG | Workspace에서도 호출(분기), recent_terminal_actions 추가 |
| `/api/v1/auth/ocp/profiles` 등 | 기존 ops console 관리 | 유지 |
| 신규 `/api/v1/workspace/status` | 사용자 ns 상태 조회 | 신규 |
| 신규 `/api/v1/workspace/pin` | 보관 토글 | 신규 |
| 신규 `/api/v1/workspace/reset` | 환경 초기화 | 신규 |
| 터미널 WS | 기존 in-app PTY → 사용자 sandbox Pod exec | 라우팅 변경 |

---

## 테스트 계획

### Python (focused)

```powershell
pytest tests/test_workspace_provisioner_unit.py
pytest tests/test_workspace_admin_api.py
pytest tests/test_terminal_ws_pod_exec.py
pytest tests/test_ops_chat_recent_terminal_actions.py
pytest tests/test_workspace_reaper_script.py
pytest tests/test_session_owner.py            # 기존 owner_hash 회귀
pytest tests/test_ops_console_api.py          # 기존 라이브 cluster chat 회귀
pytest tests/test_starter_questions.py        # v0.1.2 회귀
pytest tests/test_chat_grounding_quality.py   # v0.1.2 회귀
```

### Frontend

```powershell
npm --prefix apps/web run build
```

### Browser / Playwright

```
Workspace:
- 첫 접속 → 부트스트랩 progress → "학습 네임스페이스 …" 메시지
- 좌상단 Docs/Live 토글: 터미널 미연결 시 disable + tooltip
- mkdir/vi/oc apply 실습 + 다른 ns 403
- Live ON에서 "내 cluster의 Pod 알려줘" → 자기 ns 인용
- 동면 후 재접속 → PVC 보존 확인
- 보관하기 ON/OFF
- 환경 초기화 → 신규 발급
- 채팅 명령어 copy 후 Terminal Ctrl+V (v0.1.1 잔여 회귀)
```

### Live smoke (재배포 후)

```bash
oc rollout restart deployment/app deployment/web -n pbs-ocpops
oc rollout status deployment/app -n pbs-ocpops
oc rollout status deployment/web -n pbs-ocpops
```

---

## 완료 기준 (DoD)

1. 첫 접속자가 ID/PW/이메일 입력 없이 자기 namespace `pbs-user-<owner_hash[:8]>`의 sandbox Pod에 자동 연결된다.
2. `ls` 결과가 `/home/learner` 트리이고 PBS 앱 소스 트리가 아니다.
3. `mkdir`, `vi`, `oc apply -f`, `oc get pods` 등이 사용자 ns에서 정상 동작한다.
4. 다른 사용자 ns 자원에 대한 list/get은 403으로 차단된다.
5. 터미널 WS가 "Session exited"가 되면 Live Cluster 토글이 자동으로 disable된다.
6. Live 토글이 채팅 화면 좌측 상단에 Docs/Live 형태로 배치된다.
7. Live ON 상태에서 "내 클러스터의 Pod 알려줘" 같은 질문에 사용자 ns 기준 라이브 인용이 포함된 답변이 나온다.
8. 최근 터미널 명령/결과가 Live chat 답변에 근거로 인용될 수 있다.
9. 30분 idle 시 Pod replicas=0(동면)되고, 재접속 시 동일 PVC가 마운트되어 어제 파일이 그대로 있다.
10. 14일 미사용 + `pbs.pinned=false` 시 namespace가 자동 삭제된다. `pbs.pinned=true`면 카운터가 정지한다.
11. backend가 사용하는 클러스터 권한은 broker SA로 한정되며, `admin/admin123`은 더 이상 사용되지 않는다.
12. 사용자별 ResourceQuota/NetworkPolicy가 자동 부착된다.
13. 첫 접속 시 1회용 안내 메시지가 chat에 system 메시지로 표시된다.
14. backend focused tests가 통과한다.
15. frontend production build가 통과한다.
16. dev SNO에서 Playwright smoke + v013 신규 smoke가 통과한다.
17. v0.1.2의 회귀(studio_live_smoke, v012 beginner answer eval)가 깨지지 않는다.

---

## 위험 요소와 대응

| 위험 | 설명 | 대응 |
|---|---|---|
| 부트스트랩 latency | 첫 접속 시 namespace/SA/PVC/Pod 생성 ~10–20s | 진행 단계 progress 프레임 + 안내 메시지. 추후 warm pool로 단축 |
| 클러스터 자원 폭증 | 사용자 수 × Pod/PVC | per-user ResourceQuota + 동시 활성 상한 + 동면(replicas=0) + 14일 TTL |
| 쿠키 분실 = 환경 손실 | identity가 브라우저 쿠키 1년 한정 | 1회용 안내 + 보관하기 토글 + 미래 매직링크/SSO 확장 슬롯(`X-Forwarded-User` 헤더 1순위) 유지 |
| broker SA 권한 과대 | namespace/SA/RoleBinding/Deployment 모두 가능 | ClusterRole verb 최소화, 사용자 ns 안 자원만 patch/delete, audit log 점검 |
| sandbox 이미지 보안 | 학습용이지만 cluster API에 접근 가능 | NetworkPolicy로 외부 egress 차단, mirror registry 화이트리스트 |
| 동면 race | idle 직전 사용자가 다시 접속 | ensure 진입 시 hibernated=true이면 wake 후 ready 대기로 통일 |
| 회귀: OpsConsolePage | ops console 페이지가 같은 endpoint 공유 | recent_terminal_actions optional 필드로만 추가, 기존 호출 그대로 |
| 회귀: 기존 owner_hash | session 디렉터리/DB 경로가 owner_hash 기반 | 변경 없음, namespace 라벨에만 hash를 추가로 부착 |
| dev SNO 외 환경 차이 | 운영 환경 SNO 또는 multi-node 차이 | 첫 릴리즈는 dev SNO 한정. multi-cluster 지원은 v0.1.4 이후 |
| live chat의 namespace 권한 | broker SA가 사용자 ns를 조회하므로 정보 누출 위험 | _chat_payload에서 요청 namespace == 사용자 workspace ns 검증 강제 |

---

## 작업 메모

- 2026-05-14: `deploy/openshift/workspace-reaper-cronjob.yaml`을 추가했다. `terminal-broker` SA와 sandbox 이미지를 사용하며 15분마다 `pbs.session=true` namespace를 스캔해 30분 idle이면 `deployment/sandbox` replicas=0 및 `pbs.hibernated=true`, 14일 idle이고 `pbs.pinned=false`면 namespace를 삭제한다.
- 2026-05-14: terminal ready 프레임의 `workspace_namespace`를 `TerminalSessionPanel`에서 받아 `WorkspacePage` 상태로 올리고, Live Cluster chat payload의 `namespace`를 사용자 workspace namespace로 우선 라우팅하도록 연결했다. 사용자가 별도 namespace를 입력하지 않은 상태면 좌측 리소스 패널 namespace도 자동 발급 namespace로 맞춘다.
- 2026-05-14: sandbox 이미지를 `deploy/Dockerfile`의 `sandbox` target으로 추가하고, `.github/workflows/publish-images.yml` matrix에 `ocpops-playbookstudio-sandbox`를 포함했다. dev merge 시 app/web과 같은 태그(`dev`, `sha-*`)로 GHCR에 push된다. 이미지에는 bash, vim-minimal, less, grep, jq, 기본 curl-minimal, oc, kubectl을 포함하고 `/home/learner`를 group 0 writable로 준비했다.
- 2026-05-14: Phase C terminal WS 라우팅을 sandbox exec 방식으로 연결했다. WS 연결 시 `resolve_session_owner`로 owner_hash를 얻고 `ensure_user_workspace`를 호출한 뒤, `/app/scripts/sandbox-exec-entrypoint.sh`가 broker Pod에서 `oc exec -it -n <pbs-user-*> <sandbox-pod> -- /bin/bash -i`로 붙는다. `bootstrap_stage` 프레임(`resolving_owner`, `provisioning_workspace`, `sandbox_ready`)을 보내고, 프런트 터미널 패널은 ready 전까지 connecting 상태를 유지하면서 진행 메시지를 출력한다. 검증: `python -m compileall -q src`, `pytest tests/test_terminal_session.py tests/test_workspace_provisioner_unit.py tests/test_broker_rbac_smoke.py -q`, `bash -n deploy/scripts/terminal-entrypoint.sh`, `bash -n deploy/scripts/sandbox-exec-entrypoint.sh`, `npm --prefix apps/web run build` 통과.
- 2026-05-14: v0.1.2 smoke/report 산출물은 평가 증거일 뿐 문서 검색/추천 질문 소스가 아니어야 한다. `corpus_import.iter_corpus_source_files`에서 `reports/`, `tmp/`, `artifacts/`, `dist/`, `node_modules/` 등을 제외하도록 막았다. 서버 DB에 이미 `reports`/`smoke`/`report` 계열 document_sources 또는 document_chunks가 들어갔는지는 배포 후 SQL로 점검하고, 발견되면 해당 source와 연결 chunks를 반드시 삭제/재색인한다.
- 2026-05-14: Phase C 첫 패치로 `deploy/openshift/broker-rbac.yaml`을 추가했다. 현재 kustomize 구조에 맞춰 broker SA는 `pbs-ocpops:terminal-broker`로 두고, app Deployment만 이 SA를 사용한다. web Deployment는 기존 `playbookstudio` SA를 유지한다.
- 2026-05-14: `src/play_book_studio/cluster/workspace_provisioner.py`의 순수 manifest builder를 추가했다. 아직 cluster API apply/wait는 붙이지 않았고, Namespace/ResourceQuota/NetworkPolicy/ServiceAccount/RoleBinding/PVC/Deployment 스펙과 owner_hash→`pbs-user-<8>` 규칙을 단위 테스트로 먼저 고정했다.
- 2026-05-14: `cluster/k8s_client.py`와 provisioner lifecycle 함수를 추가했다. `ensure_user_workspace`는 in-cluster SA 토큰으로 server-side apply 후 Deployment readiness와 ready Pod를 확인하고, hibernate/wake/delete/touch/pin helper는 namespace/deployment patch/delete 경로를 사용한다. 단위 테스트는 fake client로 apply/patch/delete 순서를 검증했다.
- 2026-05-13: planner 작성. v0.1.2 Phase D 마무리(studio_live_smoke 0.85 도달, Playwright/OCP rollout)와 v0.1.3 Phase A/B를 병렬 진행 가능. C/D는 broker RBAC와 클러스터 변경이 들어가므로 순서대로.
- 2026-05-13: 사용자 식별 결정 — SMTP 부재로 매직링크/이메일은 비범위. owner_hash 쿠키(1년) 기반 익명-자동 부트스트랩으로 합의. 매직링크/SSO는 v0.1.4 이후 `resolve_session_owner` 헤더 1순위 자리에 점진 확장.
- 2026-05-13: `ops_console_api.py`의 `/api/v1/chat/query/stream`이 라이브 cluster chat 백엔드로 이미 완성되어 있음을 확인. v0.1.3은 새 백엔드를 만들지 않고 Workspace를 이 엔드포인트로 라우팅 + namespace를 사용자 workspace로 강제하는 작업으로 정의.
- 2026-05-13: WorkspacePage.tsx 라인 표시 — 토글 UI(4352-4381), `requestPayload`(3018-3034), `sendChatStream` 호출(3098), `isClusterConnected` 정의(1323), Live 강제 다운그레이드 useEffect(1377-1381). TerminalSessionPanel.tsx의 Session exited 처리(269-273)가 부모에 알리지 않는 점을 Step 2에서 콜백 prop으로 해결.
- 2026-05-14: `feat/v0.1.3/user-workspace-bootstrap` 브랜치 생성. Phase A 첫 패치로 `TerminalSessionPanel`의 `TerminalConnectionState`를 export하고 `onSessionStateChange` 콜백을 추가했다. `WorkspacePage`는 `terminalConnectionState`를 보유하며 Live Cluster 진입 조건을 `cluster connected + terminal connected`로 강화했고, 채팅 입력창 위에 있던 모드 전환을 채팅 화면 좌측 상단 `Docs / Live` 토글로 이동했다. 검증: `npm --prefix apps/web run build` 통과.
- 2026-05-14: Phase B 라우팅 완료. Workspace Live 모드 전송 경로를 `/api/chat/stream`에서 기존 `sendOpsChatStream('/api/v1/chat/query/stream')`로 분기했고, `OpsChatResponse`를 Workspace `ChatResponse`/message 형태로 변환하는 어댑터를 추가했다. 최근 터미널 명령과 output excerpt는 `recent_terminal_actions`로 payload에 포함하고 backend `_chat_payload`가 의도 분류 및 LLM context에 반영한다. 검증: `npm --prefix apps/web run build`, `python -m compileall -q src`, `pytest tests/test_ops_console_api.py -q` 통과.
