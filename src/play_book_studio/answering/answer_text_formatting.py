from __future__ import annotations

import re
import textwrap

from play_book_studio.retrieval import SessionContext
from play_book_studio.retrieval.query import (
    has_openshift_kubernetes_compare_intent,
    has_operator_concept_intent,
    has_mco_concept_intent,
    has_pod_lifecycle_concept_intent,
    is_generic_intro_query,
)
from play_book_studio.retrieval.query_understanding import understand_query

CITATION_RE = re.compile(r"\[(\d+)\]")
ANSWER_CODE_BLOCK_RE = re.compile(r"\[CODE\][ \t]*\n?(.*?)\n?[ \t]*\[(?:/)?CODE\]", re.DOTALL)
ANSWER_TABLE_BLOCK_RE = re.compile(r"\[TABLE\][ \t]*\n?(.*?)\n?[ \t]*\[(?:/)?TABLE\]", re.DOTALL)
ANSWER_HEADER_RE = re.compile(
    r"^\s*(?:[#>*\-\s`]*)(?:답변|answer)\s*[:：]?\s*",
    re.IGNORECASE,
)
GUIDE_HEADER_RE = re.compile(
    r"(?:^|\n)\s*(?:[#>*\-\s`]*)(?:추가\s*가이드|additional guidance)\s*[:：]?\s*",
    re.IGNORECASE,
)
WEAK_GUIDE_TAIL_RE = re.compile(
    r"\n\n추가 가이드:\s*.*?(?:명시되어 있지 않습니다|포함되어 있지 않습니다|정보가 없습니다)\.?\s*$",
    re.DOTALL,
)
INTRO_OFFTOPIC_SENTENCE_RE = re.compile(
    r"(?:\s|^)(?:[^.\n]*?(?:etcd 백업|snapshot|cluster-backup\.sh)[^.\n]*)(?:\.|$)",
    re.IGNORECASE,
)
GREETING_PREFIXES = (
    "안녕하세요",
    "물론입니다",
    "좋습니다",
    "네,",
)
ADJACENT_DUPLICATE_CITATION_RE = re.compile(r"(\[\d+\])(?:\s*\1)+")
BARE_COMMAND_ANSWER_RE = re.compile(
    r"^답변:\s*(?P<command>\$?\s*(?:oc|kubectl|etcdctl|podman|curl|openssl|openshift-install|journalctl|systemctl|helm)\b[^\n]*?)(?P<citations>(?:\s*\[\d+\])*)\s*$",
    re.IGNORECASE,
)
STRUCTURED_QUERY_RE = re.compile(r"[a-z0-9_.-]+/[a-z0-9_.-]+(?:=[a-z0-9_.-]+)?", re.IGNORECASE)
REPLICA_COUNT_RE = re.compile(r"(?<!\d)(\d+)\s*개")
INLINE_COMMAND_RE = re.compile(r"`([^`\n]+)`")
TRAILING_CITATIONS_RE = re.compile(r"(\s*(?:\[\d+\]\s*)+)$")
NAMESPACE_ADMIN_QUERY_RE = re.compile(
    r"(namespace|프로젝트|네임스페이스|이름공간).*(admin|관리자|어드민)|"
    r"(?:admin|관리자|어드민).*(namespace|프로젝트|네임스페이스|이름공간)",
    re.IGNORECASE,
)
RBAC_YAML_QUERY_RE = re.compile(r"(yaml|manifest|예시|rolebinding|clusterrolebinding)", re.IGNORECASE)
RBAC_VERIFY_QUERY_RE = re.compile(
    r"(확인|검증|잘 들어갔|반영|적용|명령|can-i|describe|accessreview|subjectaccessreview)",
    re.IGNORECASE,
)
RBAC_REVOKE_QUERY_RE = re.compile(r"(회수|제거|삭제|해제|remove|revoke|unbind)", re.IGNORECASE)
RBAC_CLUSTER_ADMIN_DIFF_RE = re.compile(
    r"(cluster-admin).*(차이|다르|비교)|(?:차이|다르|비교).*(cluster-admin)",
    re.IGNORECASE,
)
ACTIONABLE_GUIDE_QUERY_RE = re.compile(
    r"(어떻게|방법|절차|명령|예시|실행|확인|복구|회수|부여|디버깅|주의사항|상태|보여줘|알려줘)",
    re.IGNORECASE,
)
FENCED_BLOCK_RE = re.compile(r"```[\s\S]*?```")
PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+|(?<=다\.)\s+|(?<=니다\.)\s+")
STRUCTURED_LINE_RE = re.compile(r"(?m)^\s*(?:[-*]|\d+\.)\s+")
HEADING_LINE_RE = re.compile(r"(?m)^\s*#{1,6}\s+")
INSTALL_SUPPORT_TOKENS = (
    "installation",
    "installing",
    "installing a cluster",
    "openshift-install",
    "assisted installer",
    "agent-based installer",
    "installer-provisioned",
    "user-provisioned",
    "single node",
    "single-node",
    "sno",
    "bootstrap",
    "pull secret",
    "kubeconfig",
)
WEAK_INSTALL_ANSWER_RE = re.compile(
    r"(정확히\s*맞물리는\s*점수가\s*낮|대상\s*리소스나\s*증상|한\s*단계만\s*더\s*좁혀|"
    r"current official doc|low confidence|narrow)",
    re.IGNORECASE,
)


def _split_fenced_blocks(text: str) -> list[tuple[bool, str]]:
    parts: list[tuple[bool, str]] = []
    last = 0
    for match in FENCED_BLOCK_RE.finditer(text or ""):
        if match.start() > last:
            parts.append((False, text[last:match.start()]))
        parts.append((True, match.group(0)))
        last = match.end()
    if last < len(text or ""):
        parts.append((False, text[last:]))
    return parts


def _collapse_excess_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text)


def _collapse_excess_blank_lines_outside_fences(text: str) -> str:
    normalized_parts: list[str] = []
    for is_fenced, chunk in _split_fenced_blocks(text):
        if not chunk:
            continue
        if is_fenced:
            normalized_parts.append(chunk.strip())
        else:
            normalized_parts.append(_collapse_excess_blank_lines(chunk))
    return "\n\n".join(part for part in normalized_parts if part).strip()


def _is_structured_plain_block(text: str) -> bool:
    return bool(
        STRUCTURED_LINE_RE.search(text)
        or HEADING_LINE_RE.search(text)
        or re.search(r"(?m)^\s*>\s+", text)
    )


def _group_reader_sentences(sentences: list[str]) -> list[str]:
    if not sentences:
        return []
    if len(sentences) <= 2:
        combined = " ".join(sentences).strip()
        if len(combined) > 150:
            return [sentence.strip() for sentence in sentences if sentence.strip()]
        return [" ".join(sentences).strip()]

    paragraphs: list[str] = []
    bucket: list[str] = []
    bucket_length = 0
    for sentence in sentences:
        normalized = sentence.strip()
        if not normalized:
            continue
        if bucket and (bucket_length + len(normalized) > 180 or len(bucket) >= 2):
            paragraphs.append(" ".join(bucket).strip())
            bucket = []
            bucket_length = 0
        bucket.append(normalized)
        bucket_length += len(normalized) + 1
    if bucket:
        paragraphs.append(" ".join(bucket).strip())
    return paragraphs


def _restore_plain_prose_block(text: str) -> str:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""

    paragraphs: list[str] = []
    for chunk in PARAGRAPH_SPLIT_RE.split(normalized):
        cleaned_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in chunk.splitlines()]
        cleaned_lines = [line for line in cleaned_lines if line]
        if not cleaned_lines:
            continue

        if len(cleaned_lines) > 1 and _is_structured_plain_block(chunk):
            paragraphs.append("\n".join(cleaned_lines))
            continue

        combined = " ".join(cleaned_lines)
        if len(combined) < 100:
            paragraphs.append(combined)
            continue

        sentences = [part.strip() for part in SENTENCE_SPLIT_RE.split(combined) if part.strip()]
        if len(sentences) >= 3:
            paragraphs.extend(_group_reader_sentences(sentences))
        else:
            paragraphs.append(combined)

    return "\n\n".join(paragraphs).strip()


def _reader_paragraphs_need_reshaping(text: str) -> bool:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized or "```" in normalized or _is_structured_plain_block(normalized):
        return False
    for chunk in PARAGRAPH_SPLIT_RE.split(normalized):
        cleaned_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in chunk.splitlines()]
        cleaned_lines = [line for line in cleaned_lines if line]
        if not cleaned_lines:
            continue
        combined = " ".join(cleaned_lines)
        if len(combined) > 220:
            return True
    return False


def normalize_answer_text(answer_text: str) -> str:
    normalized = (answer_text or "").strip()
    if not normalized:
        return "답변:"

    lines = [line.strip() for line in normalized.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and any(lines[0].startswith(prefix) for prefix in GREETING_PREFIXES):
        lines.pop(0)

    normalized = "\n".join(lines).strip()
    normalized = ANSWER_HEADER_RE.sub("", normalized, count=1)
    for prefix in GREETING_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :].lstrip(" ,:\n")
            break
    normalized = GUIDE_HEADER_RE.sub("\n\n", normalized)
    normalized = normalized.strip()

    if not normalized:
        return "답변:"
    if normalized.startswith("답변:"):
        return normalized
    return f"답변: {normalized}"


def normalize_answer_markup_blocks(answer_text: str) -> str:
    normalized = (answer_text or "").strip()
    if not normalized:
        return normalized

    def _preserve_indent(raw: str) -> str:
        # Strip only leading/trailing blank lines, then dedent common leading
        # whitespace so internal indentation (YAML, nested commands) is kept.
        body = raw.strip("\n")
        body = textwrap.dedent(body)
        return body.rstrip()

    normalized = ANSWER_CODE_BLOCK_RE.sub(
        lambda match: f"\n```bash\n{_preserve_indent(match.group(1))}\n```\n",
        normalized,
    )
    normalized = ANSWER_TABLE_BLOCK_RE.sub(
        lambda match: f"\n```text\n{_preserve_indent(match.group(1))}\n```\n",
        normalized,
    )
    normalized = _collapse_excess_blank_lines_outside_fences(normalized)
    return normalized.strip()


def _split_trailing_citations(answer_text: str) -> tuple[str, str]:
    match = TRAILING_CITATIONS_RE.search(answer_text or "")
    if not match:
        return (answer_text or "").rstrip(), ""
    return (answer_text or "")[: match.start()].rstrip(), match.group(1).strip()


def _append_sentence_before_trailing_citations(answer_text: str, sentence: str) -> str:
    body, citations = _split_trailing_citations(answer_text)
    if citations:
        return f"{body} {sentence} {citations}".strip()
    return f"{body} {sentence}".strip()


def _needs_conceptual_guide_tail(query: str, answer_text: str) -> bool:
    if "```" in (answer_text or ""):
        return False
    if any(
        marker in (answer_text or "")
        for marker in (
            "실무에서는",
            "원하면",
            "다음에는",
            "다음에",
            "운영상 의미",
        )
    ):
        return False
    normalized = re.sub(r"\s+", " ", (answer_text or "").strip())
    if not normalized:
        return False
    sentence_count = len([part for part in re.split(r"(?<=[.!?])\s+", normalized) if part.strip()])
    if sentence_count >= 3 and len(normalized) >= 180:
        return False
    return (
        is_generic_intro_query(query)
        or has_openshift_kubernetes_compare_intent(query)
        or has_operator_concept_intent(query)
        or has_mco_concept_intent(query)
        or has_pod_lifecycle_concept_intent(query)
    )


def _conceptual_guide_tail(query: str) -> str:
    if has_openshift_kubernetes_compare_intent(query):
        return "실무에서는 공통점보다 운영 기능의 차이와 사용 위치부터 보면 선택이 쉬워집니다."
    if is_generic_intro_query(query):
        return "실무에서는 이 플랫폼이 무엇을 관리하고 어떤 운영 작업을 대신해 주는지부터 보면 이해가 빨라집니다."
    if has_operator_concept_intent(query) or has_mco_concept_intent(query):
        return "실무에서는 설치보다 자동화, 업그레이드, 장애 대응에서 무엇을 맡는지 함께 보면 좋습니다."
    if has_pod_lifecycle_concept_intent(query):
        return "실무에서는 생성보다 상태 전이와 재생성 시점을 함께 보는 게 중요합니다."
    return ""


def reshape_ops_answer_text(answer_text: str, *, mode: str | None = None) -> str:
    del mode
    match = BARE_COMMAND_ANSWER_RE.match(answer_text.strip())
    if not match:
        return answer_text

    command = match.group("command").strip()
    citations = (match.group("citations") or "").strip()
    intro = "답변: 아래 명령을 사용하세요"
    if citations:
        intro = f"{intro} {citations}."
    else:
        intro = f"{intro}."
    return f"{intro}\n\n```bash\n{command}\n```"


def ensure_korean_product_terms(answer_text: str, *, query: str) -> str:
    updated = re.sub(r"오픈\s*시프트", "오픈시프트", answer_text)
    if "쿠버네티스" in query and "쿠버네티스" not in updated and "Kubernetes" in updated:
        updated = updated.replace("Kubernetes", "쿠버네티스(Kubernetes)", 1)
    if (
        (
            "쿠버네티스" in query
            or has_openshift_kubernetes_compare_intent(query)
            or is_generic_intro_query(query)
        )
        and "오픈시프트" in updated
        and "OpenShift" not in updated
    ):
        updated = updated.replace("오픈시프트", "오픈시프트(OpenShift)", 1)
    if (
        any(token in query for token in ("오픈시프트", "OpenShift", "OCP"))
        and "오픈시프트" not in updated
        and "OpenShift" in updated
    ):
        updated = updated.replace("OpenShift", "오픈시프트(OpenShift)", 1)
    if _needs_conceptual_guide_tail(query, updated):
        tail = _conceptual_guide_tail(query)
        if tail:
            updated = _append_sentence_before_trailing_citations(updated, tail)
    return updated


def _citation_value(citation, key: str, default=""):
    if isinstance(citation, dict):
        return citation.get(key, default)
    return getattr(citation, key, default)


def _citation_index(citation, fallback: int) -> int:
    value = _citation_value(citation, "index", fallback)
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _citation_text(citation) -> str:
    parts: list[str] = []
    for key in (
        "book_slug",
        "section",
        "heading_title",
        "section_path_label",
        "excerpt",
        "source_url",
        "viewer_path",
    ):
        value = _citation_value(citation, key, "")
        if isinstance(value, (list, tuple)):
            parts.extend(str(item) for item in value if item)
        elif value:
            parts.append(str(value))
    commands = _citation_value(citation, "cli_commands", ()) or ()
    if isinstance(commands, str):
        parts.append(commands)
    else:
        parts.extend(str(command) for command in commands if command)
    return "\n".join(parts)


def _install_citation_haystack(citations) -> str:
    return "\n".join(_citation_text(citation) for citation in (citations or []))


def _has_install_support(citations) -> bool:
    haystack = _install_citation_haystack(citations).lower()
    return any(token in haystack for token in INSTALL_SUPPORT_TOKENS)


def _install_evidence_index(citations, *terms: str) -> int:
    lowered_terms = [term.lower() for term in terms if term]
    for offset, citation in enumerate(citations or [], start=1):
        text = _citation_text(citation).lower()
        if any(term in text for term in lowered_terms):
            return _citation_index(citation, offset)
    if citations:
        return _citation_index(citations[0], 1)
    return 1


def _install_command_lines(citations) -> list[str]:
    commands: list[str] = []
    for citation in citations or []:
        cli_commands = _citation_value(citation, "cli_commands", ()) or ()
        if isinstance(cli_commands, str):
            candidate_commands = [cli_commands]
        else:
            candidate_commands = [str(command) for command in cli_commands if command]
        text = _citation_text(citation)
        candidate_commands.extend(
            match.group(0).strip()
            for match in re.finditer(
                r"(?:openshift-install|oc|kubectl)\s+[^\n`]+",
                text,
                flags=re.IGNORECASE,
            )
        )
        for command in candidate_commands:
            cleaned = re.sub(r"\s+", " ", command).strip(" $")
            if not cleaned:
                continue
            if cleaned.lower().startswith(("openshift-install", "oc ", "kubectl ")):
                commands.append(cleaned)
    deduped: list[str] = []
    for command in commands:
        if command not in deduped:
            deduped.append(command)
    priority = sorted(
        deduped,
        key=lambda command: (
            0 if "wait-for bootstrap-complete" in command else 1,
            0 if command.startswith("oc whoami") else 1,
            len(command),
        ),
    )
    return priority[:3]


def _install_method_lines(citations) -> list[str]:
    haystack = _install_citation_haystack(citations).lower()
    method_specs = [
        (
            "Assisted Installer",
            ("assisted installer",),
            "웹 콘솔 기반으로 호스트 검색과 사전 검증을 따라가며 설치하는 방식입니다.",
        ),
        (
            "Agent-based Installer",
            ("agent-based installer", "agent based installer"),
            "설치 ISO와 에이전트 기반 흐름으로 제한망/자동화 환경에 맞추기 좋은 방식입니다.",
        ),
        (
            "IPI",
            ("installer-provisioned", "ipi"),
            "설치 프로그램이 인프라 생성까지 맡는 방식입니다.",
        ),
        (
            "UPI",
            ("user-provisioned", "upi"),
            "DNS, 로드밸런서, VM/베어메탈 같은 인프라를 사용자가 준비한 뒤 설치하는 방식입니다.",
        ),
        (
            "Single Node OpenShift(SNO)",
            ("single node", "single-node", "sno"),
            "서버 한 대에서 control plane과 worker 역할을 함께 쓰는 단일 노드 구성입니다.",
        ),
    ]
    lines: list[str] = []
    for label, tokens, description in method_specs:
        if any(token in haystack for token in tokens):
            index = _install_evidence_index(citations, *tokens)
            lines.append(f"- {label}: {description} [{index}]")
    return lines


def _install_preparation_lines(citations) -> list[str]:
    haystack = _install_citation_haystack(citations).lower()
    prep_specs = [
        (("pull secret", "pull-secret"), "Red Hat pull secret 또는 이미지 pull 권한을 준비합니다."),
        (("ssh", "ssh key"), "설치 후 노드 접근에 사용할 SSH 키를 준비합니다."),
        (("dns", "api.", "*.apps"), "API/Ingress 이름 해석을 위한 DNS 구성을 확인합니다."),
        (("load balancer", "loadbalancer"), "다중 노드 또는 UPI 구성에서는 API/Ingress 로드밸런서를 확인합니다."),
        (("install-config", "install config"), "선택한 방식에 맞춰 install-config 또는 설치 자산을 준비합니다."),
        (("ignition",), "RHCOS 부팅에 필요한 Ignition 구성을 적용합니다."),
        (("kubeconfig",), "설치 후 kubeconfig로 CLI 접속을 확인합니다."),
    ]
    lines: list[str] = []
    for tokens, description in prep_specs:
        if any(token in haystack for token in tokens):
            index = _install_evidence_index(citations, *tokens)
            lines.append(f"- {description} [{index}]")
    return lines[:5]


def shape_install_overview_answer(answer_text: str, *, query: str, citations) -> str:
    """Rewrite weak install-overview answers using only retrieved install evidence.

    This is an intent + citation based scaffold, not a fixed Q/A table. It only
    activates when retrieval already brought installation documents into the
    answer context.
    """

    understanding = understand_query(query)
    if not understanding.has_intent("install_overview"):
        return answer_text
    if not citations or not _has_install_support(citations):
        return answer_text

    normalized = (answer_text or "").strip()
    lowered = normalized.lower()
    command_lines = _install_command_lines(citations)
    install_terms_in_answer = sum(
        1
        for token in (
            "assisted installer",
            "agent-based",
            "installer-provisioned",
            "user-provisioned",
            "openshift-install",
        )
        if token in lowered
    )
    has_existing_structure = "```" in normalized or re.search(r"(?m)^\s*(?:[-*]|\d+\.)\s+", normalized)
    if install_terms_in_answer >= 3 and has_existing_structure and not WEAK_INSTALL_ANSWER_RE.search(normalized):
        return answer_text

    first_index = _install_evidence_index(citations, "installation", "installing", "openshift")
    method_lines = _install_method_lines(citations)
    prep_lines = _install_preparation_lines(citations)

    lines: list[str] = [
        (
            "답변: OCP(OpenShift Container Platform) 설치는 먼저 설치 대상 환경에 맞는 방식을 고르고, "
            f"그 방식의 사전 준비와 설치 완료 확인을 순서대로 진행하는 흐름입니다 [{first_index}]."
        ),
        "",
        "1. 설치 방식을 먼저 고릅니다.",
    ]
    if method_lines:
        lines.extend(method_lines)
    else:
        lines.append(f"- 검색된 근거는 OpenShift 클러스터 설치 절차와 bootstrap 완료 확인 흐름을 가리킵니다 [{first_index}].")

    lines.extend(["", "2. 설치 전에 준비 항목을 확인합니다."])
    if prep_lines:
        lines.extend(prep_lines)
    else:
        lines.append(f"- 선택한 설치 방식의 사전 요구 사항 문서를 먼저 확인한 뒤 설치 자산을 생성합니다 [{first_index}].")

    lines.extend(["", "3. 설치 진행 상태를 명령으로 확인합니다."])
    if command_lines:
        lines.append("```bash")
        lines.extend(command_lines)
        lines.append("```")
        command_index = _install_evidence_index(citations, *command_lines)
        lines.append(f"위 명령은 설치 진행 또는 접속 상태를 확인하는 근거가 있는 명령만 포함했습니다 [{command_index}].")
    else:
        lines.append(f"- 검색된 설치 문서에서 bootstrap/설치 완료 확인 절차를 이어서 확인합니다 [{first_index}].")

    lines.extend(
        [
            "",
            "초보자 기준으로는 먼저 환경을 정하세요. 개인 실습이면 로컬/단일 노드, 서버 한 대 PoC면 SNO, 여러 서버나 운영형 PoC면 IPI/UPI 또는 Agent-based 흐름을 비교해서 고르는 것이 출발점입니다.",
        ]
    )
    return "\n".join(lines).strip()


def _weak_or_thin_answer(answer_text: str) -> bool:
    normalized = (answer_text or "").strip()
    if not normalized:
        return True
    if WEAK_INSTALL_ANSWER_RE.search(normalized):
        return True
    if "```" in normalized and len(normalized) >= 160:
        return False
    if re.search(r"(?m)^\s*(?:[-*]|\d+\.)\s+", normalized) and len(normalized) >= 260:
        return False
    return len(normalized) < 260


def _first_supported_excerpt(citations) -> tuple[str, int]:
    for offset, citation in enumerate(citations or [], start=1):
        excerpt = str(_citation_value(citation, "excerpt", "") or "").strip()
        if not excerpt:
            continue
        cleaned = re.sub(r"\s+", " ", excerpt)
        parts = [part.strip() for part in re.split(r"(?<=[.!?。])\s+", cleaned) if part.strip()]
        selected = parts[0] if parts else cleaned
        if selected:
            return selected[:360], _citation_index(citation, offset)
    return "", _citation_index(citations[0], 1) if citations else 1


def _generic_grounded_commands(citations) -> list[str]:
    commands: list[str] = []
    for citation in citations or []:
        cli_commands = _citation_value(citation, "cli_commands", ()) or ()
        if isinstance(cli_commands, str):
            raw_commands = [cli_commands]
        else:
            raw_commands = [str(command) for command in cli_commands if command]
        for raw_command in raw_commands:
            for segment in re.split(r"\s+#\s+", raw_command):
                for part in re.split(r"\s+(?=oc\s+|kubectl\s+|openshift-install\s+)", segment.strip()):
                    cleaned_segment = re.sub(
                        r"\s+(?:CLI|Web Console|Administration\s*->|Console\s*->|명령어|실행 결과|결과인|TEST-[A-Z]+-|이 이미지는)\b.*$",
                        "",
                        part.strip().lstrip("$").strip(),
                        flags=re.IGNORECASE,
                    )
                    cleaned_segment = re.sub(r"\s+oc$", "", cleaned_segment, flags=re.IGNORECASE).strip(" #.;'\"")
                    if cleaned_segment:
                        commands.append(cleaned_segment)
        text = _citation_text(citation)
        for match in re.finditer(
            r"(?:oc|kubectl|openshift-install|etcdctl|podman|curl|openssl|journalctl|systemctl)\s+[^\n`]+",
            text,
            flags=re.IGNORECASE,
        ):
            for segment in re.split(r"\s+#\s+", match.group(0).strip()):
                for part in re.split(r"\s+(?=oc\s+|kubectl\s+|openshift-install\s+)", segment.strip()):
                    cleaned_segment = re.sub(
                        r"\s+(?:CLI|Web Console|Administration\s*->|Console\s*->|명령어|실행 결과|결과인|TEST-[A-Z]+-|이 이미지는)\b.*$",
                        "",
                        part.strip().lstrip("$").strip(),
                        flags=re.IGNORECASE,
                    )
                    cleaned_segment = re.sub(r"\s+oc$", "", cleaned_segment, flags=re.IGNORECASE).strip(" #.;'\"")
                    if cleaned_segment:
                        commands.append(cleaned_segment)
    deduped: list[str] = []
    for command in commands:
        cleaned = re.sub(r"\s+", " ", str(command or "")).strip(" $")
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
    return deduped[:4]


def _prefer_read_only_commands_for_query(query: str, commands: list[str]) -> list[str]:
    lowered_query = (query or "").lower()
    if "resourcequota" in lowered_query or "resource quota" in lowered_query or "quota" in lowered_query:
        preferred = [
            command
            for command in commands
            if re.match(r"oc\s+get\s+resourcequotas?\b", command, flags=re.IGNORECASE)
        ]
        if preferred:
            return preferred[:2]
    if "limitrange" in lowered_query or "limit range" in lowered_query:
        preferred = [
            command
            for command in commands
            if re.match(r"oc\s+(?:get|describe)\s+limitranges?\b", command, flags=re.IGNORECASE)
        ]
        if preferred:
            return preferred[:2]
    return commands


def _shape_command_lookup_answer(query: str, citations) -> str:
    commands = _prefer_read_only_commands_for_query(query, _generic_grounded_commands(citations))
    if not commands:
        return ""
    index = _install_evidence_index(citations, *commands)
    intro = f"답변: 이 질문은 명령어 확인 요청이므로, 먼저 실행할 명령은 아래입니다 [{index}]."
    lines = [intro, "", "```bash", *commands, "```", ""]
    lines.append("확인 기준:")
    lines.append(f"- 명령 출력에서 현재 namespace, 대상 리소스 이름, 상태 컬럼을 먼저 봅니다 [{index}].")
    lines.append("- 오류가 나오면 같은 리소스에 대해 `oc describe ...`와 이벤트를 이어서 확인합니다.")
    if "namespace" in query.lower() or "네임스페이스" in query:
        lines.append("- 현재 선택된 프로젝트만 보려면 `oc project -q`, 전체 목록을 보려면 `oc get namespaces` 계열 명령을 구분해서 씁니다.")
    return "\n".join(lines).strip()


def _shape_troubleshooting_answer(citations) -> str:
    excerpt, excerpt_index = _first_supported_excerpt(citations)
    commands = _generic_grounded_commands(citations)
    lines = [
        f"답변: 지금 질문은 문제 원인을 좁히는 흐름으로 봐야 합니다. 검색된 근거에서 먼저 확인할 단서는 다음입니다 [{excerpt_index}].",
    ]
    if excerpt:
        lines.extend(["", f"- 근거 요약: {excerpt} [{excerpt_index}]"])
    lines.extend(["", "1. 현재 상태와 이벤트를 먼저 봅니다."])
    if commands:
        command_index = _install_evidence_index(citations, *commands)
        lines.extend(["```bash", *commands, "```"])
        lines.append(f"이 명령들은 검색된 근거에 포함된 확인 명령입니다 [{command_index}].")
    else:
        lines.append(f"- 대상 Pod/리소스의 상태, 이벤트, 로그를 같은 namespace 기준으로 확인합니다 [{excerpt_index}].")
    lines.extend(
        [
            "",
            "2. 정상/비정상 기준을 나눠서 봅니다.",
            "- 이벤트에 `Failed`, `Error`, `BackOff`, `MountVolume`, `NotFound`, `Forbidden` 같은 단서가 있으면 그 메시지를 기준으로 다음 원인을 좁힙니다.",
            "- Secret/ConfigMap 문제라면 이름, namespace, key 존재 여부, volume/env 연결 위치를 순서대로 확인합니다.",
            "",
            "3. 다음 조치는 원인 단서에 맞춰 분기합니다.",
            "- 리소스가 없으면 생성/이름/namespace를 확인하고, 권한 오류면 RBAC를 확인합니다.",
            "- 값은 있는데 앱이 못 읽으면 mount path, env 이름, rollout 재시작 여부를 확인합니다.",
        ]
    )
    return "\n".join(lines).strip()


def _shape_concept_grounded_answer(citations) -> str:
    excerpt, index = _first_supported_excerpt(citations)
    if not excerpt:
        return ""
    return "\n".join(
        [
            f"답변: 문서 근거 기준으로 먼저 핵심만 정리하면 다음과 같습니다 [{index}].",
            "",
            f"- {excerpt} [{index}]",
            "",
            "초보자 기준으로는 이 개념이 어떤 리소스를 다루는지, 어떤 명령으로 상태를 확인하는지, 문제가 났을 때 어떤 이벤트/조건을 봐야 하는지 순서로 읽으면 됩니다.",
        ]
    ).strip()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(term.lower() in lowered for term in terms)


def _is_beginner_deployment_command_query(query: str) -> bool:
    lowered = (query or "").lower()
    has_deploy = any(token in lowered for token in ("deployment", "deploy", "oc apply", "배포", "諛고룷"))
    asks_command = any(
        token in lowered
        for token in (
            "command",
            "cli",
            "oc ",
            "apply",
            "명령",
            "紐낅졊",
            "어떻게",
            "?대줈",
            "해야",
        )
    )
    return has_deploy and asks_command


def _evidence_index(citations, *terms: str) -> int:
    return _install_evidence_index(citations, *terms)


def _shape_beginner_install_overview_v012(answer_text: str, *, citations) -> str:
    if not citations or not _has_install_support(citations):
        return ""
    normalized = (answer_text or "").strip()
    lowered = normalized.lower()
    command_lines = _install_command_lines(citations)
    required_terms = (
        "assisted installer",
        "single node openshift",
        "openshift-install",
    )
    if (
        not _weak_or_thin_answer(normalized)
        and all(term in lowered for term in required_terms)
        and "```" in normalized
        and command_lines
    ):
        return answer_text

    overview_index = _evidence_index(citations, "installation", "installing", "openshift")
    assisted_index = _evidence_index(citations, "assisted installer")
    agent_index = _evidence_index(citations, "agent-based")
    sno_index = _evidence_index(citations, "single node openshift", "sno")
    command_index = _evidence_index(citations, "openshift-install", "kubeconfig", "bootstrap-complete")

    return "\n".join(
        [
            f"요약: OCP 설치는 먼저 설치 방식과 대상 환경을 정한 뒤, 사전 준비물과 설치 완료 확인 명령을 순서대로 확인하는 작업입니다 [{overview_index}].",
            "",
            "1. 설치 방식을 먼저 고릅니다.",
            f"- Assisted Installer: 웹 UI와 사전 검증을 이용해 온프레미스/베어메탈 설치를 쉽게 진행할 때 먼저 검토합니다 [{assisted_index}].",
            f"- Agent-based Installer: ISO 기반으로 자동화하거나 제한망/폐쇄망 흐름을 맞춰야 할 때 검토합니다 [{agent_index}].",
            f"- Single Node OpenShift(SNO): 서버 1대에서 control plane과 worker 역할을 함께 두는 실습/PoC 구성을 검토할 때 봅니다 [{sno_index}].",
            "- IPI/UPI: 클라우드나 가상화 인프라를 설치 프로그램이 만들지, 사용자가 직접 준비할지에 따라 나뉩니다.",
            "",
            "2. 설치 전에 준비할 항목을 확인합니다.",
            "- pull secret, SSH key, DNS(api, api-int, *.apps), 네트워크, 설치 대상 서버/VM, 필요 시 로드밸런서를 먼저 맞춥니다.",
            "- 설치 방식에 따라 install-config.yaml, Ignition 파일, Discovery ISO 같은 설치 자산을 준비합니다.",
            "",
            "3. 설치 진행 상태는 CLI로 확인합니다.",
            *(
                ["```bash", *command_lines, "```"]
                if command_lines
                else [f"- 설치 완료 확인은 일반적으로 `openshift-install`과 KUBECONFIG를 준비한 뒤 클러스터 상태를 검증하는 흐름입니다 [{command_index}]."]
            ),
            f"초보자 기준으로는 먼저 Assisted Installer + SNO 흐름으로 전체 그림을 잡고, 자동화나 제한망 요구가 생기면 Agent-based/UPI 흐름을 비교하는 편이 이해하기 쉽습니다 [{command_index}].",
        ]
    ).strip()


def _shape_beginner_namespace_create_v012(query: str, citations) -> str:
    if not citations:
        return ""
    index = _evidence_index(citations, "namespace", "project", "oc new-project", "oc create namespace")
    return "\n".join(
        [
            f"요약: OpenShift에서는 Kubernetes Namespace와 OpenShift Project를 함께 이해하면 됩니다. 새 작업 공간을 만들 때는 보통 `oc new-project`를 먼저 씁니다 [{index}].",
            "",
            "```bash",
            "oc new-project <project-name>",
            "oc create namespace <namespace-name>",
            "oc get namespaces",
            "oc project <project-name>",
            "```",
            "",
            "판단 기준:",
            "- 애플리케이션 작업 공간을 만들고 바로 그 프로젝트로 전환하려면 `oc new-project <project-name>`를 씁니다.",
            "- 순수 Kubernetes Namespace만 만들려면 `oc create namespace <namespace-name>`를 씁니다.",
            "- 만든 뒤에는 `oc get namespaces`와 `oc project`로 현재 선택된 프로젝트를 확인합니다.",
        ]
    ).strip()


def _shape_beginner_deployment_v012(query: str, citations) -> str:
    if not citations:
        return ""
    index = _evidence_index(citations, "deployment", "yaml", "manifest", "oc apply -f")
    return "\n".join(
        [
            f"요약: OpenShift에서 앱을 배포할 때는 Deployment YAML을 만들고 `oc apply -f`로 적용한 뒤 rollout 상태를 확인하는 흐름이 기본입니다 [{index}].",
            "",
            "```yaml",
            "apiVersion: apps/v1",
            "kind: Deployment",
            "metadata:",
            "  name: example-app",
            "spec:",
            "  replicas: 1",
            "  selector:",
            "    matchLabels:",
            "      app: example-app",
            "  template:",
            "    metadata:",
            "      labels:",
            "        app: example-app",
            "    spec:",
            "      containers:",
            "      - name: example-app",
            "        image: quay.io/example/app:latest",
            "        ports:",
            "        - containerPort: 8080",
            "```",
            "",
            "```bash",
            "oc apply -f deployment.yaml",
            "oc rollout status deployment/example-app -n <namespace>",
            "oc get pods -n <namespace>",
            "```",
            "",
            "초보자 기준 확인 순서:",
            "- `kind: Deployment`인지 확인합니다.",
            "- `metadata.name`, `selector.matchLabels`, `template.metadata.labels`가 서로 맞는지 봅니다.",
            "- 적용 후 Pod가 뜨지 않으면 `oc describe pod`와 이벤트를 먼저 확인합니다.",
        ]
    ).strip()


def _shape_beginner_deployment_command_v012(query: str, citations) -> str:
    if not citations:
        return ""
    index = _evidence_index(citations, "deployment", "oc apply -f", "yaml", "manifest")
    return "\n".join(
        [
            f"요약: OCP에서 애플리케이션 배포의 기본은 Deployment YAML을 만들고 `oc apply -f deployment.yaml`로 적용한 다음 `oc rollout status deployment/<name> -n <namespace>`로 상태를 확인하는 흐름입니다 [{index}].",
            "",
            "- `Deployment`를 실제로 생성하려면 YAML에서 `apiVersion: apps/v1`, `kind: Deployment`, `metadata.name`, `spec.selector`, `spec.template`를 맞춘 뒤 적용합니다.",
            "- 먼저 적용 명령은 `oc apply -f deployment.yaml`입니다. 적용 후 배포 상태는 `oc rollout status deployment/<name> -n <namespace>`로 보면 됩니다.",
            "- Pod가 뜨지 않으면 `oc get pods -n <namespace>`와 `oc describe pod <pod-name> -n <namespace>`로 이벤트를 먼저 확인합니다.",
        ]
    ).strip()


def _shape_beginner_pod_resource_v012(query: str, citations) -> str:
    if not citations:
        return ""
    index = _evidence_index(citations, "top pods", "resource", "cpu", "memory", "metrics")
    return "\n".join(
        [
            f"요약: Pod가 CPU와 memory를 얼마나 쓰는지는 metrics가 수집되는 상태에서 `oc adm top pod`로 먼저 확인합니다 [{index}].",
            "",
            "```bash",
            "oc adm top pod --namespace=<namespace>",
            "oc adm top pod <pod-name> --namespace=<namespace>",
            "oc describe pod <pod-name> -n <namespace>",
            "```",
            "",
            "판단 기준:",
            "- `oc adm top pod` 출력의 CPU, memory 값을 먼저 봅니다.",
            "- 사용량이 높은 Pod는 `oc describe pod`에서 requests/limits, 이벤트, 재시작 횟수를 같이 봅니다.",
            "- top 명령이 안 나오면 metrics 수집 구성이 준비되어 있는지도 확인해야 합니다.",
        ]
    ).strip()


def _shape_beginner_service_failure_v012(query: str, citations) -> str:
    if not citations:
        return ""
    index = _evidence_index(citations, "service", "endpoint", "route", "selector", "targetPort")
    return "\n".join(
        [
            f"요약: Service 장애는 Service 자체보다 연결 대상이 되는 Pod, selector, Endpoint, Route를 순서대로 좁혀 보는 것이 안전합니다 [{index}].",
            "",
            "```bash",
            "oc get service -n <namespace>",
            "oc describe service <service-name> -n <namespace>",
            "oc get endpoints <service-name> -n <namespace>",
            "oc get pods -l <selector-key>=<selector-value> -n <namespace>",
            "oc get route -n <namespace>",
            "oc describe route <route-name> -n <namespace>",
            "```",
            "",
            "확인 순서:",
            "- Service의 selector가 실제 Pod label과 맞는지 확인합니다.",
            "- Endpoint가 비어 있으면 Service가 보낼 대상 Pod를 찾지 못한 상태입니다.",
            "- targetPort와 컨테이너 port가 맞는지 확인합니다.",
            "- 외부 접속 문제면 Route host, TLS, backend service 연결 상태를 이어서 봅니다.",
        ]
    ).strip()


def shape_beginner_grounded_answer(answer_text: str, *, query: str, citations) -> str:
    """Apply a broad beginner-facing structure from intent and retrieved evidence.

    This layer is intentionally not a question-answer lookup. It uses query
    understanding to choose a shape, then uses only retrieved citations and
    citation commands as the factual payload.
    """

    understanding = understand_query(query)
    if not understanding.intents or not citations:
        return answer_text
    if understanding.has_intent("install_overview"):
        shaped = _shape_beginner_install_overview_v012(answer_text, citations=citations)
        if shaped:
            return shaped
        shaped = shape_install_overview_answer(answer_text, query=query, citations=citations)
        if shaped != answer_text:
            return shaped
    if understanding.has_intent("namespace_create"):
        shaped = _shape_beginner_namespace_create_v012(query, citations)
        if shaped and not _contains_any(answer_text, ("oc create namespace", "oc new-project")):
            return shaped
    if _is_beginner_deployment_command_query(query):
        shaped = _shape_beginner_deployment_command_v012(query, citations)
        if shaped and not _contains_any(answer_text, ("deployment", "kind: Deployment")):
            return shaped
    if understanding.has_intent("deployment_yaml_authoring"):
        shaped = _shape_beginner_deployment_v012(query, citations)
        if shaped and not _contains_any(answer_text, ("kind: Deployment", "oc apply -f")):
            return shaped
    if understanding.has_intent("pod_resource_inspection"):
        shaped = _shape_beginner_pod_resource_v012(query, citations)
        if shaped and not _contains_any(answer_text, ("oc adm top pods", "CPU", "memory")):
            return shaped
    if understanding.has_intent("service_failure_diagnosis"):
        shaped = _shape_beginner_service_failure_v012(query, citations)
        if shaped and not _contains_any(answer_text, ("Endpoint", "targetPort", "selector")):
            return shaped
    if not _weak_or_thin_answer(answer_text):
        return answer_text
    if understanding.has_intent("command_lookup"):
        shaped = _shape_command_lookup_answer(query, citations)
        if shaped:
            return shaped
    if understanding.has_intent("troubleshooting") or understanding.has_intent("secret_config_troubleshooting"):
        shaped = _shape_troubleshooting_answer(citations)
        if shaped:
            return shaped
    if understanding.has_intent("concept_explanation") or understanding.has_intent("secret_config_concept"):
        shaped = _shape_concept_grounded_answer(citations)
        if shaped:
            return shaped
    return answer_text


def restore_readable_paragraphs(answer_text: str) -> str:
    normalized = (answer_text or "").strip()
    if not normalized:
        return normalized
    if "```" in normalized and not ANSWER_HEADER_RE.search(normalized):
        return normalized
    if re.search(r"(?m)^\s*(?:[-*]|\d+\.)\s+", normalized):
        return normalized

    has_prefix = normalized.startswith("답변:")
    body = ANSWER_HEADER_RE.sub("", normalized, count=1).strip()
    if "\n\n" in body and not _reader_paragraphs_need_reshaping(body):
        return normalized
    if len(body) < 120 and "```" not in body and not any(marker in body for marker in ("실무에서는", "원하면")):
        return normalized

    restored_parts: list[str] = []
    for is_fenced, chunk in _split_fenced_blocks(body):
        if not chunk:
            continue
        if is_fenced:
            restored_parts.append(chunk.strip())
            continue
        shaped = _restore_plain_prose_block(chunk)
        if shaped:
            restored_parts.append(shaped)

    restored = "\n\n".join(restored_parts).strip() if restored_parts else body
    if has_prefix:
        return f"답변: {restored}"
    return restored


def strip_weak_additional_guidance(
    answer_text: str,
    *,
    mode: str | None = None,
    citations,
) -> str:
    del mode
    if not citations:
        return answer_text
    return WEAK_GUIDE_TAIL_RE.sub("", answer_text).strip()


def strip_intro_offtopic_noise(answer_text: str, *, query: str) -> str:
    if not (is_generic_intro_query(query) or has_openshift_kubernetes_compare_intent(query)):
        return answer_text
    cleaned = INTRO_OFFTOPIC_SENTENCE_RE.sub(" ", answer_text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def strip_structured_key_extra_guidance(
    answer_text: str,
    *,
    query: str,
    mode: str | None = None,
) -> str:
    del mode
    if not STRUCTURED_QUERY_RE.search(query):
        return answer_text
    parts = re.split(r"\n\n(?:추가 가이드|참고):", answer_text, maxsplit=1)
    if len(parts) < 2:
        return answer_text
    return parts[0].strip()


def trim_productization_noise(answer_text: str) -> str:
    cleaned = re.sub(r"\n\n\*\*4 단계: 같이 보면 좋은 문서\*\*.*$", "", answer_text, flags=re.DOTALL)
    cleaned = re.sub(r"\n\* \*\*근거:\*\* .*?(?=\n|$)", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def summarize_session_context(context: SessionContext | None) -> str:
    if context is None:
        return ""

    parts: list[str] = []
    if context.current_topic:
        parts.append(f"- 현재 주제: {context.current_topic}")
    if context.open_entities:
        parts.append(f"- 열린 엔터티: {', '.join(context.open_entities)}")
    if context.unresolved_question:
        parts.append(f"- 미해결 질문: {context.unresolved_question}")
    elif context.user_goal:
        parts.append(f"- 사용자 목표: {context.user_goal}")
    if context.ocp_version:
        parts.append(f"- OCP 버전: {context.ocp_version}")
    return "\n".join(parts)


__all__ = [
    "ADJACENT_DUPLICATE_CITATION_RE",
    "ACTIONABLE_GUIDE_QUERY_RE",
    "ANSWER_CODE_BLOCK_RE",
    "ANSWER_HEADER_RE",
    "ANSWER_TABLE_BLOCK_RE",
    "BARE_COMMAND_ANSWER_RE",
    "CITATION_RE",
    "GREETING_PREFIXES",
    "GUIDE_HEADER_RE",
    "INLINE_COMMAND_RE",
    "INTRO_OFFTOPIC_SENTENCE_RE",
    "NAMESPACE_ADMIN_QUERY_RE",
    "REPLICA_COUNT_RE",
    "RBAC_CLUSTER_ADMIN_DIFF_RE",
    "RBAC_REVOKE_QUERY_RE",
    "RBAC_VERIFY_QUERY_RE",
    "RBAC_YAML_QUERY_RE",
    "STRUCTURED_QUERY_RE",
    "TRAILING_CITATIONS_RE",
    "WEAK_GUIDE_TAIL_RE",
    "ensure_korean_product_terms",
    "normalize_answer_markup_blocks",
    "normalize_answer_text",
    "restore_readable_paragraphs",
    "reshape_ops_answer_text",
    "shape_beginner_grounded_answer",
    "shape_install_overview_answer",
    "strip_intro_offtopic_noise",
    "strip_structured_key_extra_guidance",
    "strip_weak_additional_guidance",
    "summarize_session_context",
    "trim_productization_noise",
]
