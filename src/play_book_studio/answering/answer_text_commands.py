from __future__ import annotations

import re

from play_book_studio.retrieval import SessionContext
from play_book_studio.retrieval.query import (
    has_backup_restore_intent,
    has_certificate_monitor_intent,
    has_cluster_node_usage_intent,
    has_command_request,
    has_corrective_follow_up,
    has_deployment_scaling_intent,
    has_first_step_intent,
    has_node_drain_intent,
    has_openshift_kubernetes_compare_intent,
    has_project_finalizer_intent,
    has_project_terminating_intent,
    has_rbac_assignment_intent,
    has_rbac_intent,
    has_pod_pending_troubleshooting_intent,
    has_pod_lifecycle_concept_intent,
    is_generic_intro_query,
)

from .answer_text_formatting import (
    ACTIONABLE_GUIDE_QUERY_RE,
    ANSWER_HEADER_RE,
    CITATION_RE,
    INLINE_COMMAND_RE,
    NAMESPACE_ADMIN_QUERY_RE,
    REPLICA_COUNT_RE,
    RBAC_CLUSTER_ADMIN_DIFF_RE,
    RBAC_REVOKE_QUERY_RE,
    RBAC_VERIFY_QUERY_RE,
    RBAC_YAML_QUERY_RE,
)

RBAC_FOLLOW_UP_HINT_RE = re.compile(
    r"(권한|rbac|rolebinding|clusterrolebinding|clusterrole|\brole\b|admin|cluster-admin|namespace|프로젝트|네임스페이스|이름공간)",
    re.IGNORECASE,
)
ETCD_FOLLOW_UP_ISSUE_RE = re.compile(
    r"(문제|오류|실패|막히|안 되|안되|어디부터|점검|확인|복원|restore)",
    re.IGNORECASE,
)
RBAC_VERIFY_FOLLOW_UP_RE = re.compile(
    r"(확인|검증|잘 들어갔|반영|적용|can-i|describe|accessreview|subjectaccessreview)",
    re.IGNORECASE,
)
RBAC_IDENTIFIER_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
RBAC_PROJECT_VALUE_PATTERNS = (
    re.compile(
        r"(?P<value>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:이라는|라는)?\s*(?:프로젝트|project|namespace|네임스페이스|이름공간)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:프로젝트|project|namespace|네임스페이스|이름공간)\s*(?:이름은?\s*)?(?P<value>[A-Za-z0-9][A-Za-z0-9._-]*)",
        re.IGNORECASE,
    ),
)
RBAC_USER_VALUE_PATTERNS = (
    re.compile(
        r"(?P<value>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:사용자|유저|계정|그룹|serviceaccount|서비스\s*계정)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:사용자|유저|계정|그룹|serviceaccount|서비스\s*계정)\s*(?:이름은?\s*)?(?P<value>[A-Za-z0-9][A-Za-z0-9._-]*)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<value>[A-Za-z0-9][A-Za-z0-9._-]*)(?:를|을|에게)\s*(?:관리자|어드민|\badmin\b|edit|view|cluster-admin)",
        re.IGNORECASE,
    ),
)
_COMMAND_TOKEN_RE = re.compile(
    r"\b(?:oc(?:\s+adm)?\s+[a-z0-9-]+(?:\s+[a-z0-9-]+)?|kubectl\s+[a-z0-9-]+(?:\s+[a-z0-9-]+)?|lsblk|df\s+-h|journalctl|must-gather)\b",
    re.IGNORECASE,
)
_DISK_QUERY_RE = re.compile(r"(디스크|disk|filesystem|파일시스템|lsblk|df\s+-h)", re.IGNORECASE)
_NODE_ACCESS_QUERY_RE = re.compile(r"(노드.*접속|접속.*노드|host.*access|ssh|oc debug|debug\s+명령)", re.IGNORECASE)
_LOG_QUERY_RE = re.compile(r"(로그|log|journal|node-logs|must-gather)", re.IGNORECASE)


def _citation_text(citation) -> str:
    parts: list[str] = [
        str(getattr(citation, "section", "") or ""),
        str(getattr(citation, "excerpt", "") or ""),
    ]
    parts.extend(str(command or "") for command in (getattr(citation, "cli_commands", ()) or ()))
    return "\n".join(part for part in parts if part).lower()


def _should_use_generic_first_step_answer(query: str) -> bool:
    if not has_first_step_intent(query):
        return False
    if (
        has_backup_restore_intent(query)
        or has_certificate_monitor_intent(query)
        or has_cluster_node_usage_intent(query)
        or has_deployment_scaling_intent(query)
        or has_node_drain_intent(query)
        or has_openshift_kubernetes_compare_intent(query)
        or has_pod_pending_troubleshooting_intent(query)
        or has_pod_lifecycle_concept_intent(query)
        or has_project_finalizer_intent(query)
        or has_project_terminating_intent(query)
        or has_rbac_intent(query)
        or is_generic_intro_query(query)
    ):
        return False
    return True


def _query_command_tokens(query: str) -> set[str]:
    return {
        re.sub(r"\s+", " ", match.group(0).strip().lower())
        for match in _COMMAND_TOKEN_RE.finditer(query or "")
    }


def has_sufficient_command_grounding(*, query: str, citations) -> bool:
    if not citations:
        return False
    lowered_query = (query or "").lower()
    citation_texts = [_citation_text(citation) for citation in citations]
    joined = "\n".join(citation_texts)

    explicit_commands = _query_command_tokens(lowered_query)
    if explicit_commands and not any(token in joined for token in explicit_commands):
        return False

    if _NODE_ACCESS_QUERY_RE.search(lowered_query):
        if not any(
            any(token in text for token in ("oc debug", "chroot /host", "node debug", "ssh", "host access"))
            for text in citation_texts
        ):
            return False

    if _DISK_QUERY_RE.search(lowered_query):
        if not any(
            any(token in text for token in ("lsblk", "df -h", "filesystem", "disk", "디스크", "파일시스템"))
            for text in citation_texts
        ):
            return False

    if _LOG_QUERY_RE.search(lowered_query) and not _DISK_QUERY_RE.search(lowered_query):
        if not any(
            any(token in text for token in ("node-logs", "must-gather", "journal", "로그", "log"))
            for text in citation_texts
        ):
            return False

    return True


def align_answer_to_grounded_commands(answer_text: str, *, query: str, citations) -> str:
    excerpt_text = "\n".join((citation.excerpt or "") for citation in citations).lower()
    updated = answer_text

    if has_cluster_node_usage_intent(query) and "oc adm top nodes" in excerpt_text:
        return (
            "답변: `oc adm top nodes`는 클러스터 전체 노드의 CPU와 메모리 사용량을 빠르게 훑어볼 때 먼저 쓰는 명령입니다 [1].\n\n"
            "노드 과부하, 리소스 불균형, 드레인이나 점검 전에 현재 사용량을 확인해야 할 때 유용합니다 [1]. "
            "특정 노드만 보고 싶으면 `oc adm top node <node-name>` 형태로 좁혀서 확인하면 됩니다 [1].\n\n"
            "```bash\noc adm top nodes\n```"
        )

    if has_node_drain_intent(query) and "oc adm drain" in excerpt_text:
        updated = re.sub(r"\bkubectl\s+drain\b", "oc adm drain", updated, flags=re.IGNORECASE)
        supporting_texts = [answer_text, excerpt_text]
        for citation in citations:
            supporting_texts.extend(citation.cli_commands or ())
        grounded_commands = _extract_grounded_commands(*supporting_texts, limit=4)
        drain_command = next(
            (command for command in grounded_commands if command.lower().startswith("oc adm drain")),
            "oc adm drain <노드명> --ignore-daemonsets --delete-emptydir-data",
        )
        uncordon_command = next(
            (command for command in grounded_commands if command.lower().startswith("oc adm uncordon")),
            "",
        )
        detail = (
            "`--ignore-daemonsets` 사용 여부와 `--delete-emptydir-data`로 인한 로컬 데이터 삭제 영향을 "
            "먼저 확인한 뒤 drain 해야 합니다 [1]."
        )
        if uncordon_command:
            return (
                "답변: 점검 전에는 아래 명령으로 해당 노드를 안전하게 drain 하면 됩니다 [1].\n\n"
                f"```bash\n{drain_command}\n```\n\n"
                f"{detail}\n\n"
                "점검이 끝나면 아래 명령으로 다시 스케줄링을 허용합니다 [1].\n\n"
                f"```bash\n{uncordon_command}\n```"
            )
        return (
            "답변: 점검 전에는 아래 명령으로 해당 노드를 안전하게 drain 하면 됩니다 [1].\n\n"
            f"```bash\n{drain_command}\n```\n\n"
            f"{detail}"
        )

    if has_certificate_monitor_intent(query) and "monitor-certificates" in excerpt_text:
        return (
            "답변: 플랫폼 인증서 만료 상태는 아래 명령으로 모니터링해 확인합니다 [1].\n\n"
            "```bash\noc adm ocp-certificates monitor-certificates\n```"
        )

    if (
        NAMESPACE_ADMIN_QUERY_RE.search(query or "")
        and has_rbac_intent(query)
        and "add-role-to-user admin" in excerpt_text
    ):
        subject_user, subject_project = _extract_rbac_assignment_targets(query)
        generic_command = "oc adm policy add-role-to-user admin <user> -n <project>"
        if subject_user and subject_project:
            return (
                f"답변: `{subject_project}` 프로젝트의 `{subject_user}` 사용자에게 `admin` 역할을 주려면 "
                "아래 명령을 실행하면 됩니다 [1].\n\n"
                f"```bash\noc adm policy add-role-to-user admin {subject_user} -n {subject_project}\n```\n\n"
                "같은 패턴의 일반형은 아래와 같습니다 [1].\n\n"
                f"```bash\n{generic_command}\n```"
            )
        return (
            "답변: 특정 프로젝트 또는 namespace에만 `admin` 권한을 주려면 먼저 아래 명령으로 "
            "로컬 역할 바인딩을 추가합니다 [1].\n\n"
            f"```bash\n{generic_command}\n```\n\n"
            "예를 들어 `joe` 프로젝트의 `alice` 사용자에게 `admin` 역할을 주려면 아래처럼 실행하면 됩니다 [1].\n\n"
            "```bash\noc adm policy add-role-to-user admin alice -n joe\n```"
        )

    return updated


def _looks_like_shell_command(value: str) -> bool:
    normalized = (value or "").strip().lstrip("$").strip().lower()
    if not normalized:
        return False
    return normalized.startswith(
        (
            "oc ",
            "kubectl ",
            "tkn ",
            "etcdctl ",
            "helm ",
            "curl ",
            "openssl ",
            "journalctl ",
            "systemctl ",
            "chroot ",
            "/usr/local/bin/",
            "cluster-backup.sh",
            "cluster-restore.sh",
        )
    )


def _ordered_citation_commands(citation, *, limit: int = 3) -> list[str]:
    commands: list[str] = []
    seen: set[str] = set()

    for command in (getattr(citation, "cli_commands", ()) or ()):
        normalized = (command or "").strip().lstrip("$").strip()
        if not _looks_like_shell_command(normalized):
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        commands.append(normalized)
        if len(commands) >= limit:
            return commands

    if commands:
        return commands

    return _extract_grounded_commands(str(getattr(citation, "excerpt", "") or ""), limit=limit)


def _extract_grounded_commands(*texts: str, limit: int = 3) -> list[str]:
    commands: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        normalized = (candidate or "").strip().lstrip("$").strip()
        if not _looks_like_shell_command(normalized):
            return
        if normalized in seen:
            return
        seen.add(normalized)
        commands.append(normalized)

    for text in texts:
        for match in INLINE_COMMAND_RE.finditer(text or ""):
            add(match.group(1))
        for raw_line in (text or "").splitlines():
            if raw_line.strip().startswith("#"):
                continue
            line = raw_line.strip().lstrip("-*").strip()
            add(line)
        if len(commands) >= limit:
            break

    return commands[:limit]


def _collect_ordered_grounded_commands(citations, *, limit: int = 3) -> list[str]:
    commands: list[str] = []
    seen: set[str] = set()

    for citation in citations:
        for command in _ordered_citation_commands(citation, limit=limit):
            key = command.casefold()
            if key in seen:
                continue
            seen.add(key)
            commands.append(command)
            if len(commands) >= limit:
                return commands

    return commands


def _first_grounded_command_citation_index(citations) -> int:
    for index, citation in enumerate(citations, start=1):
        if _ordered_citation_commands(citation, limit=1):
            return index
    return 1


def build_first_step_grounded_answer(
    *,
    query: str,
    citations,
) -> str | None:
    if not citations or not _should_use_generic_first_step_answer(query):
        return None

    first_citation_index = _first_grounded_command_citation_index(citations)
    primary_citation = citations[first_citation_index - 1]
    commands = _collect_ordered_grounded_commands(citations[first_citation_index - 1 :], limit=2)
    if not commands:
        return None

    primary_ref = citation_marker(citations, first_citation_index)
    section = (primary_citation.section or "").strip()
    section_prefix = f"`{section}` 절차 기준으로 " if section else ""
    follow_up = ""
    if len(commands) > 1:
        follow_up = f"\n\n첫 단계가 끝나면 같은 절차의 다음 명령으로 이어가면 됩니다 {primary_ref}."

    return (
        f"답변: {section_prefix}가장 먼저 아래 명령으로 시작하면 됩니다 {primary_ref}.\n\n"
        f"```bash\n{commands[0]}\n```\n\n"
        f"질문이 첫 단계 확인형이므로 뒤 단계 명령보다 이 명령을 먼저 확인하면 됩니다 {primary_ref}."
        f"{follow_up}"
    )


def guard_first_step_grounding(
    answer_text: str,
    *,
    query: str,
    citations,
) -> str:
    expected_answer = build_first_step_grounded_answer(
        query=query,
        citations=citations,
    )
    if expected_answer is None:
        return answer_text

    expected_commands = _collect_ordered_grounded_commands(citations, limit=1)
    if not expected_commands:
        return answer_text

    answer_commands = _extract_grounded_commands(answer_text, limit=1)
    if not answer_commands:
        return expected_answer
    if answer_commands[0].casefold() != expected_commands[0].casefold():
        return expected_answer
    return answer_text


def _actionable_intro(query: str) -> str:
    if has_backup_restore_intent(query):
        return "답변: 절차는 아래 순서로 실행하면 됩니다"
    if has_project_terminating_intent(query) or has_project_finalizer_intent(query):
        return "답변: 먼저 남아 있는 리소스와 상태를 아래 명령으로 확인하면 됩니다"
    if has_rbac_intent(query):
        return "답변: 필요한 작업은 아래 명령으로 바로 처리할 수 있습니다"
    if has_certificate_monitor_intent(query):
        return "답변: 아래 명령으로 상태를 바로 확인하면 됩니다"
    if has_node_drain_intent(query):
        return "답변: 작업은 아래 명령 기준으로 진행하면 됩니다"
    if has_cluster_node_usage_intent(query):
        return "답변: 아래 명령으로 상태를 바로 확인하면 됩니다"
    if has_deployment_scaling_intent(query):
        return "답변: 아래 명령으로 바로 조정하면 됩니다"
    if has_command_request(query) or has_corrective_follow_up(query):
        return "답변: 실행 예시는 아래 명령을 기준으로 보면 됩니다"
    return "답변: 아래 명령으로 진행하면 됩니다"


def _supporting_sentence_without_commands(answer_text: str) -> str:
    stripped = INLINE_COMMAND_RE.sub("", answer_text or "")
    stripped = CITATION_RE.sub("", stripped)
    stripped = ANSWER_HEADER_RE.sub("", stripped, count=1)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    if not stripped:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", stripped)
    for sentence in sentences:
        candidate = sentence.strip()
        if not candidate:
            continue
        if _looks_like_shell_command(candidate):
            continue
        if 12 <= len(candidate) <= 140:
            return candidate
    return ""


def shape_actionable_ops_answer(
    answer_text: str,
    *,
    query: str,
    citations,
) -> str:
    if "```" in (answer_text or ""):
        return answer_text
    if not (
        has_backup_restore_intent(query)
        or has_project_terminating_intent(query)
        or has_project_finalizer_intent(query)
        or has_certificate_monitor_intent(query)
        or has_cluster_node_usage_intent(query)
        or has_node_drain_intent(query)
        or has_rbac_intent(query)
        or has_deployment_scaling_intent(query)
        or has_command_request(query)
        or has_corrective_follow_up(query)
    ):
        return answer_text

    excerpt_text = "\n".join((citation.excerpt or "") for citation in citations)
    commands = _extract_grounded_commands(answer_text, excerpt_text, limit=2)
    if not commands:
        return answer_text

    intro = _actionable_intro(query)
    blocks = "\n\n".join(f"```bash\n{command}\n```" for command in commands)
    detail = _supporting_sentence_without_commands(answer_text)
    if detail:
        return f"{intro} [1].\n\n{blocks}\n\n{detail} [1]."
    return f"{intro} [1].\n\n{blocks}"


def build_grounded_command_guide_answer(
    *,
    query: str,
    citations,
) -> str | None:
    if not citations:
        return None
    first_step_answer = build_first_step_grounded_answer(
        query=query,
        citations=citations,
    )
    if first_step_answer is not None:
        return first_step_answer
    if (
        has_backup_restore_intent(query)
        or has_project_terminating_intent(query)
        or has_project_finalizer_intent(query)
        or has_certificate_monitor_intent(query)
        or has_cluster_node_usage_intent(query)
        or has_node_drain_intent(query)
        or has_rbac_intent(query)
        or has_pod_pending_troubleshooting_intent(query)
    ):
        return None
    if is_generic_intro_query(query) or has_openshift_kubernetes_compare_intent(query):
        return None
    if not (
        ACTIONABLE_GUIDE_QUERY_RE.search(query or "")
        or has_command_request(query)
        or has_corrective_follow_up(query)
    ):
        return None
    if not has_sufficient_command_grounding(query=query, citations=citations):
        return None

    commands = _collect_ordered_grounded_commands(citations, limit=2)
    if not commands:
        return None

    primary = citations[0]
    intro = _actionable_intro(query)
    code_blocks = "\n\n".join(f"```bash\n{command}\n```" for command in commands)
    section = (primary.section or "").strip()
    if section:
        return (
            f"{intro} [1].\n\n"
            f"{section} 절차 기준으로 먼저 아래 명령부터 확인하거나 실행하면 됩니다 [1].\n\n"
            f"{code_blocks}"
        )
    return f"{intro} [1].\n\n{code_blocks}"


def _rbac_grounded_excerpt_text(citations) -> str:
    return "\n".join(
        f"{citation.book_slug or ''}\n{citation.section or ''}\n{citation.excerpt or ''}" for citation in citations
    ).lower()


def _has_grounded_rbac_citation(citations) -> bool:
    excerpt_text = _rbac_grounded_excerpt_text(citations)
    for citation in citations:
        book_slug = (citation.book_slug or "").lower()
        if book_slug in {
            "authentication_and_authorization",
            "authorization_apis",
            "api_overview",
            "tutorials",
            "ai_workloads",
        }:
            return True
    return any(
        token in excerpt_text
        for token in (
            "rolebinding",
            "clusterrolebinding",
            "add-role-to-user",
            "remove-role-from-user",
            "cluster-admin",
            "localsubjectaccessreview",
            "selfsubjectaccessreview",
            "selfsubjectrulesreview",
            "subjectaccessreview",
        )
    )


def _has_explicit_rbac_follow_up_query(query: str) -> bool:
    normalized = query or ""
    return bool(
        RBAC_YAML_QUERY_RE.search(normalized)
        or RBAC_REVOKE_QUERY_RE.search(normalized)
        or RBAC_CLUSTER_ADMIN_DIFF_RE.search(normalized)
        or _is_rbac_verify_follow_up_query(normalized)
    )


def _has_rbac_assignment_query(query: str) -> bool:
    normalized = query or ""
    return bool(
        has_rbac_assignment_intent(normalized)
        or (NAMESPACE_ADMIN_QUERY_RE.search(normalized) and has_rbac_intent(normalized))
    )


def _is_rbac_verify_follow_up_query(query: str) -> bool:
    normalized = query or ""
    if _has_rbac_assignment_query(normalized):
        return False
    return bool(
        RBAC_VERIFY_FOLLOW_UP_RE.search(normalized)
        and RBAC_FOLLOW_UP_HINT_RE.search(normalized)
    )


def _clean_rbac_identifier(raw_value: str | None) -> str | None:
    value = (raw_value or "").strip().strip("`'\"“”‘’")
    value = re.sub(r"^[<(]+", "", value)
    value = re.sub(r"[>)]+$", "", value)
    value = re.sub(r"[.,!?]+$", "", value)
    if not value:
        return None
    if value.lower() in {
        "user",
        "project",
        "namespace",
        "admin",
        "rolebinding",
        "clusterrolebinding",
    }:
        return None
    if not RBAC_IDENTIFIER_VALUE_RE.fullmatch(value):
        return None
    return value


def _extract_rbac_value(query: str, patterns: tuple[re.Pattern[str], ...]) -> str | None:
    normalized = query or ""
    for pattern in patterns:
        match = pattern.search(normalized)
        if not match:
            continue
        cleaned = _clean_rbac_identifier(match.group("value"))
        if cleaned:
            return cleaned
    return None


def _extract_rbac_assignment_targets(query: str) -> tuple[str | None, str | None]:
    return (
        _extract_rbac_value(query, RBAC_USER_VALUE_PATTERNS),
        _extract_rbac_value(query, RBAC_PROJECT_VALUE_PATTERNS),
    )


def shape_rbac_follow_up_answer(
    answer_text: str,
    *,
    query: str,
    citations,
) -> str:
    lowered_query = (query or "").lower()
    if not _has_explicit_rbac_follow_up_query(query):
        return answer_text
    if not citations or not _has_grounded_rbac_citation(citations):
        return answer_text

    excerpt_text = _rbac_grounded_excerpt_text(citations)

    if RBAC_YAML_QUERY_RE.search(query or ""):
        subject_user, subject_project = _extract_rbac_assignment_targets(query)
        namespace_value = subject_project or "<project>"
        user_value = subject_user or "<user>"
        return (
            "답변: 특정 namespace에만 `admin` 권한을 주는 `RoleBinding` YAML 예시는 아래처럼 작성하면 됩니다 [1].\n\n"
            "```yaml\n"
            "apiVersion: rbac.authorization.k8s.io/v1\n"
            "kind: RoleBinding\n"
            "metadata:\n"
            "  name: admin-0\n"
            f"  namespace: {namespace_value}\n"
            "roleRef:\n"
            "  apiGroup: rbac.authorization.k8s.io\n"
            "  kind: ClusterRole\n"
            "  name: admin\n"
            "subjects:\n"
            "- apiGroup: rbac.authorization.k8s.io\n"
            "  kind: User\n"
            f"  name: {user_value}\n"
            "```\n\n"
            "작성한 YAML은 아래 명령으로 적용하면 됩니다 [1].\n\n"
            "```bash\noc apply -f rolebinding.yaml\n```"
        )

    if _is_rbac_verify_follow_up_query(query):
        _, subject_project = _extract_rbac_assignment_targets(query)
        project_value = subject_project or "<project>"
        return (
            "답변: 권한이 잘 들어갔는지 보려면 먼저 해당 namespace의 RoleBinding을 확인하는 명령부터 쓰면 됩니다 [1].\n\n"
            f"```bash\noc describe rolebinding.rbac -n {project_value}\n```\n\n"
            "사용자 입장에서 실제 허용 권한을 더 확인해야 하면 `SelfSubjectRulesReview` 또는 `SelfSubjectAccessReview` 계열 API로 점검할 수 있습니다 [1]."
        )

    if RBAC_REVOKE_QUERY_RE.search(query or "") and "remove-role-from-user" in excerpt_text:
        subject_user, subject_project = _extract_rbac_assignment_targets(query)
        user_value = subject_user or "<user>"
        project_value = subject_project or "<project>"
        return (
            "답변: 특정 namespace에 준 `admin` 권한을 회수하려면 아래 명령으로 로컬 역할 바인딩을 제거하면 됩니다 [1].\n\n"
            f"```bash\noc adm policy remove-role-from-user admin {user_value} -n {project_value}\n```"
        )

    if RBAC_CLUSTER_ADMIN_DIFF_RE.search(query or "") or ("cluster-admin" in lowered_query and "admin" in lowered_query):
        return (
            "답변: `admin`은 특정 프로젝트 또는 namespace 안에서 리소스를 관리하는 로컬 관리자 권한이고, `cluster-admin`은 클러스터 전역을 관리하는 최상위 권한입니다 [1].\n\n"
            "`oc adm policy add-role-to-user admin <user> -n <project>`처럼 프로젝트 범위로 바인딩하면 그 namespace 안에서만 강한 권한을 주는 것이고, "
            "진짜 클러스터 전체 관리자 권한은 `ClusterRoleBinding`으로 `cluster-admin`을 묶어야 합니다 [1]."
        )

    return answer_text


def shape_etcd_backup_answer(
    answer_text: str,
    *,
    query: str,
    citations,
) -> str:
    query_text = query or ""
    excerpt_text = "\n".join(
        f"{citation.book_slug or ''}\n{citation.section or ''}\n{citation.excerpt or ''}"
        for citation in citations
    ).lower()
    has_grounded_backup_section = any(
        (citation.book_slug or "").lower() in {"postinstallation_configuration", "backup_and_restore", "etcd"}
        and "etcd" in (citation.section or "").lower()
        and ("백업" in (citation.section or "").lower() or "backup" in (citation.section or "").lower())
        for citation in citations
    )
    has_grounded_restore_section = any(
        (citation.book_slug or "").lower() in {"postinstallation_configuration", "backup_and_restore", "etcd"}
        and (
            (
                "etcd" in (citation.section or "").lower()
                and ("복원" in (citation.section or "").lower() or "restore" in (citation.section or "").lower())
            )
            or any(
                token in f"{citation.section or ''}\n{citation.excerpt or ''}".lower()
                for token in (
                    "이전 클러스터 상태로 복원",
                    "cluster-restore.sh",
                    "disable-etcd.sh",
                    "etcd 백업",
                    "정적 pod의 리소스",
                )
            )
        )
        for citation in citations
    )
    backup_citation_index = next(
        (
            index
            for index, citation in enumerate(citations, start=1)
            if (citation.book_slug or "").lower() in {"postinstallation_configuration", "backup_and_restore", "etcd"}
            and "etcd" in (citation.section or "").lower()
            and ("백업" in (citation.section or "").lower() or "backup" in (citation.section or "").lower())
        ),
        1,
    )
    restore_citation_index = next(
        (
            index
            for index, citation in enumerate(citations, start=1)
            if (citation.book_slug or "").lower() in {"postinstallation_configuration", "backup_and_restore", "etcd"}
            and (
                (
                    "etcd" in (citation.section or "").lower()
                    and ("복원" in (citation.section or "").lower() or "restore" in (citation.section or "").lower())
                )
                or any(
                    token in f"{citation.section or ''}\n{citation.excerpt or ''}".lower()
                    for token in (
                        "이전 클러스터 상태로 복원",
                        "cluster-restore.sh",
                        "disable-etcd.sh",
                        "정적 pod의 리소스",
                    )
                )
            )
        ),
        1,
    )
    backup_ref = citation_marker(citations, backup_citation_index)
    restore_ref = citation_marker(citations, restore_citation_index)
    companion_citation_index = next(
        (
            index
            for index, citation in enumerate(citations, start=1)
            if index != backup_citation_index
            and (citation.book_slug or "").lower() in {"etcd", "backup_and_restore"}
            and "etcd" in (citation.section or "").lower()
            and any(
                token in (citation.section or "").lower()
                for token in ("백업", "backup", "복원", "restore")
            )
        ),
        None,
    )
    companion_ref = (
        citation_marker(citations, companion_citation_index)
        if companion_citation_index is not None
        else ""
    )
    intro_refs = (
        f"{backup_ref}{companion_ref}"
        if companion_ref and companion_ref != backup_ref
        else backup_ref
    )
    companion_note = (
        f"\n\n표준 절차는 설치 후 구성 문서를 기준으로 따르고, 전용 etcd 문서는 같은 작업의 전용 맥락과 복구 절차를 같이 확인할 때 참조하면 됩니다 {companion_ref}."
        if companion_ref and companion_ref != backup_ref
        else ""
    )
    has_restore_signal = bool(re.search(r"(복원|복구|restore)", query_text, re.IGNORECASE))
    if not re.search(r"(백업|backup|복원|복구|restore)", query_text, re.IGNORECASE):
        return answer_text
    if "etcd" not in query_text.lower() and not (has_grounded_backup_section or has_grounded_restore_section):
        return answer_text
    if has_grounded_restore_section and has_restore_signal:
        restore_commands = _extract_grounded_commands(excerpt_text, limit=3)
        restore_command = next(
            (
                command
                for command in restore_commands
                if "restore" in command.lower() or "etcdctl snapshot restore" in command.lower()
            ),
            restore_commands[0] if restore_commands else "ETCDCTL_API=3 /usr/bin/etcdctl snapshot restore <snapshot.db>",
        )
        follow_up_check = next(
            (
                command
                for command in restore_commands
                if command != restore_command and ("crictl ps" in command.lower() or "mv " in command.lower())
            ),
            None,
        )
        follow_up_block = ""
        if follow_up_check is not None:
            follow_up_block = (
                f"\n\n복원 명령을 적용한 뒤에는 etcd 컨테이너와 정적 pod 상태를 이어서 확인합니다 {restore_ref}.\n\n"
                f"```bash\n{follow_up_check}\n```"
            )
        return (
            f"답변: etcd 복원은 백업 디렉터리와 스냅샷을 준비한 뒤 복원 명령을 순서대로 실행하면 됩니다 {restore_ref}.\n\n"
            f"각 컨트롤 플레인 호스트에 백업 디렉터리를 준비한 다음, 복원 호스트에서 아래 명령으로 이전 클러스터 상태를 복원합니다 {restore_ref}.\n\n"
            f"```bash\n{restore_command}\n```"
            f"{follow_up_block}"
        )
    if has_grounded_backup_section and re.search(r"(백업|backup|복원|복구|restore)", query_text, re.IGNORECASE):
        if ETCD_FOLLOW_UP_ISSUE_RE.search(query_text):
            return (
                f"답변: etcd 백업이나 복원 중 막히면 먼저 작업을 수행한 컨트롤 플레인 노드에서 절차가 실제로 끝까지 수행됐는지 순서대로 다시 확인하면 됩니다 {intro_refs}.\n\n"
                "1. 디버그 세션과 호스트 진입이 정상인지 다시 확인합니다.\n\n"
                "```bash\noc debug --as-root node/<node_name>\nchroot /host\n```\n\n"
                f"2. 백업 단계라면 `cluster-backup.sh` 실행 지점과 저장 위치를 기준으로 어느 단계에서 끊겼는지 먼저 확인합니다 {backup_ref}.\n\n"
                "```bash\n/usr/local/bin/cluster-backup.sh /home/core/assets/backup\n```\n\n"
                f"3. 복원 단계라면 방금 수행한 단계의 출력과 사용 중인 절차 문서를 맞춰 보면서 실패한 지점부터 좁혀야 합니다 {backup_ref}.{companion_note}"
            )
        if "etcd" not in query_text.lower():
            return (
                f"답변: etcd 백업은 컨트롤 플레인 노드에서 아래 순서로 진행하면 됩니다 {intro_refs}.\n\n"
                "1. 디버그 세션을 시작합니다.\n\n"
                "```bash\noc debug --as-root node/<node_name>\n```\n\n"
                "2. 호스트 루트로 전환합니다.\n\n"
                "```bash\nchroot /host\n```\n\n"
                "3. 백업 스크립트를 실행합니다.\n\n"
                "```bash\n/usr/local/bin/cluster-backup.sh /home/core/assets/backup\n```\n\n"
                f"백업 파일은 단일 컨트롤 플레인 호스트에서만 저장해야 합니다 {backup_ref}.{companion_note}"
            )
    if (
        "cluster-backup.sh" not in excerpt_text
        and "etcdctl snapshot save" not in excerpt_text
        and "oc debug --as-root node" not in excerpt_text
        and not has_grounded_backup_section
    ):
        return answer_text
    return (
        f"답변: etcd 백업은 컨트롤 플레인 노드에서 아래 순서로 진행하면 됩니다 {intro_refs}.\n\n"
        "1. 디버그 세션을 시작합니다.\n\n"
        "```bash\noc debug --as-root node/<node_name>\n```\n\n"
        "2. 호스트 루트로 전환합니다.\n\n"
        "```bash\nchroot /host\n```\n\n"
        "3. 백업 스크립트를 실행합니다.\n\n"
        "```bash\n/usr/local/bin/cluster-backup.sh /home/core/assets/backup\n```\n\n"
        f"백업 파일은 단일 컨트롤 플레인 호스트에서만 저장해야 합니다 {backup_ref}.{companion_note}"
    )


def shape_project_termination_answer(
    answer_text: str,
    *,
    query: str,
    citations,
) -> str:
    if not (has_project_terminating_intent(query) or has_project_finalizer_intent(query)):
        return answer_text
    if not citations:
        return answer_text

    excerpt_text = "\n".join(
        f"{citation.book_slug or ''}\n{citation.section or ''}\n{citation.excerpt or ''}"
        for citation in citations
    )
    commands = _extract_grounded_commands(excerpt_text, limit=2)
    if not commands:
        return answer_text

    primary_ref = citation_marker(citations, 1)
    secondary_ref = citation_marker(citations, 2) if len(citations) > 1 else primary_ref
    first_block = f"```bash\n{commands[0]}\n```"
    second_block = ""
    if len(commands) > 1:
        second_block = f"\n\n```bash\n{commands[1]}\n```"

    if has_project_finalizer_intent(query):
        return (
            f"답변: 먼저 종료 중 상태와 관련 네임스페이스/리소스를 아래 명령으로 확인하는 순서로 진행하면 됩니다 {primary_ref}.\n\n"
            f"{first_block}{second_block}\n\n"
            f"관련 리소스나 finalizer 정리 전에는 어떤 오브젝트가 종료를 막고 있는지부터 확인해야 합니다 {secondary_ref}."
        )

    return (
        f"답변: `Terminating`에 머무는 프로젝트는 먼저 종료 중인 네임스페이스와 관련 리소스 상태를 확인하는 순서로 접근하면 됩니다 {primary_ref}.\n\n"
        f"{first_block}{second_block}\n\n"
        f"프로젝트 삭제 자체는 CLI 또는 웹 콘솔에서 다시 요청할 수 있고, 종료 중인 동안에는 새 콘텐츠를 추가할 수 없습니다 {secondary_ref}."
    )


def shape_certificate_monitor_answer(
    answer_text: str,
    *,
    query: str,
    citations,
) -> str:
    excerpt_text = "\n".join((citation.excerpt or "") for citation in citations).lower()
    if not has_certificate_monitor_intent(query):
        return answer_text
    if "monitor-certificates" not in excerpt_text:
        return answer_text
    return (
        "답변: 플랫폼 인증서 만료 상태는 `oc adm ocp-certificates monitor-certificates` 명령으로 모니터링해 확인합니다 [1].\n\n"
        "```bash\noc adm ocp-certificates monitor-certificates\n```"
    )


def citation_marker(citations, index: int) -> str:
    if not citations:
        return ""
    bounded = index if 1 <= index <= len(citations) else 1
    return f"[{bounded}]"


def shape_pod_lifecycle_explainer(
    answer_text: str,
    *,
    query: str,
    mode: str | None = None,
    citations,
) -> str:
    del mode
    if not has_pod_lifecycle_concept_intent(query) or not citations:
        return answer_text

    primary = citations[0]
    secondary = citations[1] if len(citations) > 1 else citations[0]
    primary_ref = citation_marker(citations, 1)
    secondary_ref = citation_marker(citations, 2)

    return (
        f"답변: Pod 라이프사이클은 Pod가 생성되고 노드에 배치된 뒤 실행되다가, 종료되면 제거되거나 다시 만들어지는 흐름입니다 {primary_ref}.\n\n"
        f"- 생성/배치: Pod가 만들어지면 먼저 어느 노드에서 실행할지 결정되고 그 노드에 배치됩니다 {primary_ref}.\n"
        f"- 실행: Pod는 실행 중 직접 수정하기보다 기존 Pod를 종료하고 새 Pod를 다시 만드는 방식으로 변경을 반영합니다 {primary_ref}.\n"
        f"- 종료/교체: 종료 이유와 로그를 함께 봐야 하고, `{secondary.section}` 문서는 생성 뒤 자동으로 채워지는 특성과 예시를 같이 보여 줍니다 {secondary_ref}."
    )


def shape_pod_pending_troubleshooting(
    answer_text: str,
    *,
    query: str,
    mode: str | None = None,
    citations,
) -> str:
    del mode
    if not has_pod_pending_troubleshooting_intent(query) or not citations:
        return answer_text

    primary = citations[0]
    secondary = citations[1] if len(citations) > 1 else citations[0]
    secondary_section = secondary.section or primary.section or "이벤트 목록"
    primary_ref = citation_marker(citations, 1)
    secondary_ref = citation_marker(citations, 2)
    intro_refs = primary_ref if primary_ref == secondary_ref else f"{primary_ref}{secondary_ref}"

    return (
        f"답변: Pod가 `Pending`이면 가장 먼저 해당 Pod의 `Events`에서 `FailedScheduling` 같은 예약 실패 이유를 확인하면 됩니다 {intro_refs}.\n\n"
        f"1. `oc describe pod <pod-name> -n <pod-namespace>`로 `Events`를 보고 어떤 이유가 반복되는지 먼저 봅니다 {primary_ref}.\n"
        f"2. `{secondary_section}`처럼 node affinity, selector, taint/toleration 같은 스케줄링 제약이 맞는지 확인합니다 {secondary_ref}.\n"
        f"3. 이벤트가 리소스 부족이나 볼륨 바인딩 문제를 가리키면 그 메시지를 기준으로 다음 점검 대상을 좁히면 됩니다 {primary_ref}."
    )


def has_grounded_deployment_scale_citation(citations) -> bool:
    for citation in citations:
        lowered_section = (citation.section or "").lower()
        lowered_excerpt = (citation.excerpt or "").lower()
        if citation.book_slug == "cli_tools" and (
            "oc scale" in lowered_section
            or "oc scale" in lowered_excerpt
            or "deployment/" in lowered_excerpt
        ):
            return True
    return False


def extract_replica_counts(query: str) -> list[int]:
    explicit = [int(match.group(1)) for match in REPLICA_COUNT_RE.finditer(query or "")]
    if explicit:
        return explicit
    return [int(token) for token in re.findall(r"(?<![\w.])(\d+)(?![\w.])", query or "")]


def deployment_scaling_signal(query: str, context: SessionContext | None) -> bool:
    if has_deployment_scaling_intent(query):
        return True
    if context is None:
        return False
    if (context.current_topic or "").strip() == "Deployment 스케일링":
        return True
    return has_deployment_scaling_intent(context.user_goal or "")


def build_deployment_scaling_answer(
    *,
    query: str,
    context: SessionContext | None,
    citations,
) -> str | None:
    if not deployment_scaling_signal(query, context):
        return None
    if not has_grounded_deployment_scale_citation(citations):
        if has_command_request(query) or has_corrective_follow_up(query):
            return (
                "답변: 지금 검색된 근거가 `Deployment` 스케일 명령으로 바로 이어지지 않아 "
                "명령을 단정하기 어렵습니다. `deployment/my-app을 5개에서 10개로`처럼 "
                "대상 Deployment와 목표 복제본 수를 함께 다시 말해 주세요."
            )
        return None

    counts = extract_replica_counts(query)
    if not counts:
        if has_command_request(query) or has_corrective_follow_up(query):
            return (
                "답변: 지금은 몇 개로 바꾸려는지 숫자가 현재 질문에 없습니다. "
                "예를 들어 `5개에서 10개로 변경하는 명령어`처럼 목표 복제본 수를 함께 알려주세요."
            )
        return None

    target = counts[-1]
    if len(counts) >= 2:
        current = counts[0]
        command = (
            f"oc scale --current-replicas={current} --replicas={target} "
            "deployment/<deployment-name>"
        )
        return (
            "답변: 실행 중인 Deployment의 복제본 수를 바꾸려면 `oc scale` 명령으로 "
            f"현재 값 {current}개에서 목표 값 {target}개로 조정하면 됩니다 [1].\n\n"
            f"```bash\n{command}\n```\n\n"
            f"* 범위: 지정한 Deployment의 Pod 수만 {target}개로 조정됩니다.\n"
            f"* 예시: `oc scale --current-replicas={current} --replicas={target} deployment/my-app` [1]"
        )

    command = f"oc scale deployment/<deployment-name> --replicas={target}"
    return (
        "답변: 실행 중인 Deployment의 복제본 수를 바꾸려면 `oc scale` 명령으로 "
        f"목표 값을 {target}개로 지정하면 됩니다 [1].\n\n"
        f"```bash\n{command}\n```\n\n"
        f"* 범위: 지정한 Deployment의 Pod 수만 {target}개로 조정됩니다.\n"
        f"* 예시: `oc scale deployment/my-app --replicas={target}` [1]"
    )


__all__ = [
    "align_answer_to_grounded_commands",
    "build_first_step_grounded_answer",
    "build_deployment_scaling_answer",
    "build_grounded_command_guide_answer",
    "citation_marker",
    "deployment_scaling_signal",
    "extract_replica_counts",
    "guard_first_step_grounding",
    "has_grounded_deployment_scale_citation",
    "has_sufficient_command_grounding",
    "shape_actionable_ops_answer",
    "shape_certificate_monitor_answer",
    "shape_etcd_backup_answer",
    "shape_pod_lifecycle_explainer",
    "shape_pod_pending_troubleshooting",
    "shape_project_termination_answer",
    "shape_rbac_follow_up_answer",
]
