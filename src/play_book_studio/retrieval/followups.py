"""후속 질문 신호와 문맥 참조 판별 helper를 모아 둔 모듈이다.

`query.py`에서 follow-up 계열 규칙만 떼어내, retrieval query 정책 파일의 책임을 조금 더 좁힌다.
"""

from __future__ import annotations

import re


SPACE_RE = re.compile(r"\s+")
DEMONSTRATIVE_TOPIC_RE = re.compile(
    r"^(?:그|저|이)\s+(?:operator|오퍼레이터|복구|복원|설정|문서|방법|절차|재부팅|이유|내용|명령|주제|보안|인증서|로그|권한|역할|rolebinding|role binding|yaml|yml|admin|어드민|cluster-admin)(?:는|은|가|이|를|을|와|과|도|만)?",
    re.IGNORECASE,
)

FOLLOW_UP_HINTS = (
    "그거",
    "그걸",
    "그건",
    "그게",
    "저거",
    "그 설정",
    "그 문서",
    "그 내용",
    "그 권한",
    "그 역할",
    "거기서",
    "그 상태에서",
    "안 되는데",
    "안되는데",
    "걸려",
    "남아",
    "아까",
    "이전",
    "해당",
    "1번",
    "2번",
    "3번",
    "rolebinding",
    "yaml 예시",
)

CORRECTIVE_FOLLOW_UP_HINTS = (
    "아니",
    "그게 아니라",
    "그 말 말고",
    "다시",
    "정확히",
    "그러니까",
    "명령어라도",
    "커맨드라도",
)

FOLLOW_UP_COMPARE_RE = re.compile(
    r"(차이도|비교도).*(설명|말해|정리|알려|보여)",
    re.IGNORECASE,
)
FOLLOW_UP_PARTITIVE_RE = re.compile(
    r"^(?:그\s*중(?:에서)?|그중(?:에서)?|그\s*안(?:에서)?|그안(?:에서)?)(?:\s|$)",
    re.IGNORECASE,
)
CONTEXTUAL_FOLLOW_UP_ACTION_RE = re.compile(
    r"((관련\s+)?(실행\s*예시|주의사항|상태\s*확인\s*방법|(?:진행\s*)?상태를?\s*확인하는\s*방법|삭제\s*진행\s*상태).*(같이|함께|알려|보여|정리))|"
    r"((복원\s*절차|백업\s*파일이\s*정상인지\s*확인하는\s*방법|권한이\s*잘\s*들어갔는지\s*확인하는\s*명령|권한을\s*회수).*(알려|보여|정리|확인))",
    re.IGNORECASE,
)
RBAC_EXAMPLE_FOLLOW_UP_RE = re.compile(
    r"(예를\s*들어|예시로|실제로).*((프로젝트|project|네임스페이스|namespace|이름공간).*(사용자|유저|계정|serviceaccount|서비스\s*계정)|(사용자|유저|계정|serviceaccount|서비스\s*계정).*(프로젝트|project|네임스페이스|namespace|이름공간)).*(admin|관리자|어드민|edit|view|cluster-admin|권한|역할)",
    re.IGNORECASE,
)


def _collapse_spaces(text: str) -> str:
    return SPACE_RE.sub(" ", (text or "")).strip()


def has_corrective_follow_up(query: str) -> bool:
    normalized = _collapse_spaces(query)
    lowered = normalized.lower()
    if any(hint in normalized for hint in CORRECTIVE_FOLLOW_UP_HINTS):
        return True
    return lowered.startswith(("아니", "그게 아니라", "다시", "정확히", "그러니까"))


def has_follow_up_reference(query: str) -> bool:
    normalized = _collapse_spaces(query)
    lowered = normalized.lower()
    if has_corrective_follow_up(normalized):
        return True
    if FOLLOW_UP_PARTITIVE_RE.search(normalized):
        return True
    if RBAC_EXAMPLE_FOLLOW_UP_RE.search(normalized):
        return True
    if CONTEXTUAL_FOLLOW_UP_ACTION_RE.search(normalized):
        return True
    if FOLLOW_UP_COMPARE_RE.search(normalized):
        return True
    if DEMONSTRATIVE_TOPIC_RE.search(normalized):
        return True
    if any(hint in normalized for hint in FOLLOW_UP_HINTS):
        return True
    return lowered.startswith(
        (
            "그리고",
            "그럼",
            "그러면",
            "이어서",
            "그 다음",
            "또 ",
            "찾았는데도",
            "거기서",
            "그 상태에서",
        )
    )
