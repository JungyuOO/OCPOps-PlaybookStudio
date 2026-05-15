# UI Salvage Operation

작성일: 2026-05-15
작업 브랜치: `feat/dev-ui`
참조 브랜치: `feat/dev-kugnus-test`

## Goal

`feat/dev-kugnus-test`에 들어갔던 UI 개선 중, dev에 올리기 안전한 부분만 `feat/dev-ui`로 옮긴다.
J가 백엔드/챗봇/Ops 작업에 집중할 수 있게, backend migration/API 실험은 가져오지 않는다.

## Keep

- 공통 AppHeader 방향성
- landing/library/studio의 theme toggle 위치 통일
- 우측 profile 위치 통일
- library 문서 card overflow 수정
- Reader modal dark/light theme 연동
- library visual density 개선 중 API 계약을 바꾸지 않는 CSS/TSX 조정

## Exclude

- 실험적 upload pipeline event ledger
- topology snapshot migration/API
- chat feedback metadata spine migration/API
- quality snapshot DB migration
- 긴 이름의 실험 migration 파일
- backend contract가 필요한 UI 상태 조작

## Acceptance

- base는 clean `origin/dev` 계열이어야 한다.
- `db/migrations`는 J의 `0000`-`0009` 흐름을 건드리지 않는다.
- UI 변경은 기존 API가 없으면 fake 성공처럼 보이게 만들지 않는다.
- `npm exec tsc -- --noEmit -p tsconfig.app.json`와 `npm run build`를 통과해야 한다.
- library/studio/landing을 브라우저에서 light/dark로 확인한다.

## Work Order

1. 현재 `feat/dev-ui`에서 dev 최신 상태를 확인한다.
2. `feat/dev-kugnus-test`의 UI diff만 파일 단위로 분리한다.
3. backend/API/migration 의존 diff는 제외한다.
4. header/theme/profile/read modal/card overflow 순서로 작은 단위 적용한다.
5. 타입체크, 빌드, 브라우저 확인 후 PR로 올린다.
