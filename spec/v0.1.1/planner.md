# v0.1.1 초보자 중심 시작 질문 및 터미널 입력 UX 개선

## 목표

v0.1.1은 PlayBookStudio를 OCP를 한 번도 설치하거나 배포해 본 적 없는 초보자 기준으로 다시 맞춘다.

시작 질문은 문서 제목, 내부 단계명, `Day-2` 같은 운영자 용어를 그대로 보여주지 않는다. 실제 사용자가 물어볼 법한 말투로 보여주되, 질문 자체는 하드코딩된 Q/A 목록이 아니라 문서/청크의 제목, 학습 목표, source terms, manifest metadata에서 근거를 가져와 생성한다.

동시에 Studio Terminal에서 긴 명령어가 여러 줄로 wrap된 상태에서 Backspace/Delete를 눌렀을 때 이전 줄까지 자연스럽게 지워지도록 터미널 입력/렌더링 흐름을 고친다.

## 원칙

- 하드코딩된 예상 질문과 답변 매핑은 금지한다.
- 추천 질문은 청크/문서 메타데이터에서 주제와 의도를 추출한 뒤 초보자 자연어로 작문한다.
- 사용자는 `Day-2`, `postinstallation_configuration`, 내부 guide id를 모른다고 가정한다.
- 초보자는 설치, namespace, Pod, Service, Deployment, Route, Secret, ConfigMap 개념도 모를 수 있다.
- 질문 로그는 실패 분석과 추후 품질 개선 용도이며, 즉시 RAG 입력이나 추천 질문 소스로 쓰지 않는다.
- 문자 인코딩과 콘솔 출력은 UTF-8 기준으로 유지한다.
- OCP 배포 환경 재배포 후 smoke 검증은 다음 단계로 이월한다.

## Core

- [x] v0.1.1 브랜치 생성
- [x] `spec/v0.1.1/planner.md` 생성
- [x] v0.1.0 배포 smoke 이월 상태 기록
- [x] 현재 starter question 생성 경로 재점검
- [x] 깨진 한글 테스트 문자열 UTF-8로 복구
- [x] FAQ/learning/operations 시작 질문의 고정 카테고리 문장 제거
- [x] 청크 metadata 기반 초보자 질문 작문 로직 추가
- [x] 시작 질문이 요청 seed마다 rotate되는지 테스트 추가
- [x] 시작 질문이 문서 제목만 붙인 문장이 아닌지 테스트 추가
- [x] Playwright smoke에서 발견한 영어 내부 term/troubleshoot 노출과 청크 제목 suffix 노출 수정
- [x] 실운영 문서 제목 fallback에서 `보기`, `확인하기` 같은 섹션 suffix 제거
- [x] Terminal Session을 Linux 배포 환경에서 PTY 기반으로 실행하도록 변경
- [x] xterm cols/rows resize를 서버 PTY에 전달하도록 변경
- [x] 로컬 `docker-compose.yml` web 포트/healthcheck를 nginx `listen 8080` 기준으로 정렬
- [x] 터미널 paste/Ctrl+V 기존 동작 회귀 방지 확인
- [x] starter question focused tests 실행
- [x] frontend build 실행
- [x] Playwright로 로컬 Studio 시작 질문 smoke 확인
- [x] 유효한 OCP 토큰 환경에서 Terminal wrap/backspace 수동 smoke 확인

## 시작 질문 개선 방향

문제 예시:

```text
Day-2 단계에서는 설치 후 구성 기준으로 무엇을 순서대로 학습하면 돼?
```

초보자에게 더 자연스러운 방향:

```text
설치가 끝난 다음에는 뭘 먼저 확인하면 돼?
클러스터가 정상인지 확인하는 명령어가 뭐야?
처음 앱을 올리려면 namespace부터 어떻게 만들면 돼?
Pod, Service, Route는 각각 뭘 하는 거야?
배포한 앱이 안 뜨면 어디부터 봐야 해?
Secret이랑 ConfigMap은 언제 쓰는 거야?
```

중요한 점은 위 문장을 그대로 고정 목록으로 쓰는 것이 아니라, 문서 category, source terms, learning goal, chunk title에서 주제와 의도를 뽑아 초보자 자연어 질문으로 변환하는 것이다.

## 터미널 개선 방향

증상:

```text
긴 명령어를 입력해서 두 줄 이상 wrap된 상태에서 지우면,
터미널 커서와 표시가 이전 줄로 자연스럽게 이어지지 않는다.
```

확인 결과:

- 기존 백엔드는 bash를 실제 PTY가 아니라 stdin/stdout pipe로 실행했다.
- 이 구조에서는 bash/readline이 브라우저 xterm의 실제 cols/rows를 알 수 없어 wrap된 입력 삭제가 깨질 수 있다.
- 프론트엔드도 xterm fit 이후 resize 정보를 서버로 보내지 않고 있었다.

수정 방향:

- Linux 배포 환경에서는 `pty.openpty()` 기반으로 shell을 실행한다.
- xterm `onResize`와 `FitAddon.fit()` 결과를 WebSocket `resize` 메시지로 서버에 보낸다.
- 서버는 받은 cols/rows를 `TIOCSWINSZ`로 PTY에 반영한다.
- Windows 개발 환경은 기존 pipe 실행 fallback을 유지한다.

## 검증 계획

```powershell
pytest tests/test_starter_questions.py tests/test_starter_questions_readable.py
npm --prefix apps/web run build
```

가능하면 다음 단계에서 배포 환경 smoke를 진행한다.

```text
1. Studio Chat 첫 화면 시작 질문 확인
2. 새로고침/다른 사용자 seed에서 질문 rotate 확인
3. Terminal Session에서 120자 이상 명령 입력
4. Backspace로 wrap된 이전 줄까지 삭제되는지 확인
5. Ctrl+V paste 회귀 확인
```

## 작업 메모

- 2026-05-11: v0.1.0의 OCP 배포 smoke는 실제 배포 단계로 이월했다.
- 2026-05-11: v0.1.1 작업 브랜치 `feat/v0.1.1/beginner-starters-terminal`을 생성했다.
- 2026-05-11: 고정 카테고리별 시작 질문 문장을 제거하고, 문서/청크 context 기반 질문 작문기로 전환했다.
- 2026-05-11: Terminal Session은 Linux에서 PTY로 실행하고 xterm resize를 서버에 전달하도록 수정했다.
- 2026-05-11: `pytest tests/test_starter_questions.py tests/test_starter_questions_readable.py -q --basetemp tmp/pytest` 통과.
- 2026-05-11: `python -m py_compile`로 변경 Python 모듈 문법 검증 통과.
- 2026-05-11: `npm --prefix apps/web run build` 통과. Vite chunk size warning은 기존 번들 크기 경고로 남아 있다.
- 2026-05-11: Playwright smoke 중 로컬 compose가 nginx 8080 리슨 설정과 다르게 `8080:80`으로 매핑되어 `ERR_EMPTY_RESPONSE`가 나는 문제를 발견했다. 루트 compose의 web 포트와 healthcheck를 8080 기준으로 수정했다.
- 2026-05-11: Playwright snapshot에서 `troubleshoot가...`, `노드 상태 검증부터 보기...`처럼 내부 term/title 흔적이 남는 것을 확인했다. troubleshooting/node 주제 추출을 추가해 초보자 질문으로 다시 변환하도록 보정했다.
- 2026-05-11: 재확인 중 `사업 범위와 추진 배경 보기`, `아키텍처 구성 결과 확인하기`처럼 문서 섹션 suffix가 노출되는 것을 확인했다. 제목 fallback을 subject로 쓸 때 suffix를 제거하도록 수정했다.
- 2026-05-11: Playwright snapshot 기준 시작 질문은 `노드 상태는 처음에 어디서 확인하면 돼?`, `앱 배포는 처음에 어떤 순서로 진행하면 돼?`, `PVC와 볼륨은 뭔지부터 알고 싶은데 어디서 확인하면 돼?` 형태로 확인했다.
- 2026-05-11: 터미널은 현재 로컬 `.env`의 OCP token이 만료되어 세션이 즉시 종료된다. 로컬 shell fallback 없이 클러스터 재연결 안내가 뜨는 것은 확인했지만, wrap/backspace와 paste는 유효 토큰 환경에서 재확인이 필요하다.
- 2026-05-11: `.env` 토큰 갱신 후 app/web을 재기동했고, Playwright snapshot에서 `OpenShift CLI login ready`와 shell prompt를 확인했다.
- 2026-05-11: synthetic paste 이벤트와 실제 Ctrl+V clipboard 입력을 모두 확인했다. `echo PASTE_OK_2`, `echo CTRLV_OK`가 터미널에서 실행되어 출력됐다.
- 2026-05-11: 180자 이상 긴 명령어를 wrap 상태로 입력한 뒤 `BAD` 3글자를 Backspace로 삭제하고 `OK`를 입력했다. 화면 wrap이 깨지지 않았고 실행 결과에도 삭제된 `BAD`가 남지 않았다.
