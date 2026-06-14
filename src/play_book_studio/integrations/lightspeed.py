"""OpenShift Lightspeed API client and routing helpers."""

from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass, field
from typing import Any

import requests

from play_book_studio.config.settings import Settings


OPENSHIFT_OPERATION_RE = re.compile(
    r"("
    r"openshift|오픈\s*시프트|오픈시프트|(?<![a-z0-9])ocp(?![a-z0-9])|"
    r"kubernetes|쿠버네티스|"
    r"\boc\s+|kubectl|yaml|manifest|apply|"
    r"pod|파드|포드|pvc|pv|node|노드|route|루트|ingress|"
    r"service|svc|서비스\s*(연결|포트|엔드\s*포인트|라우팅|노출|상태)|"
    r"container|컨테이너|"
    r"namespace|네임스페이스|project|프로젝트|"
    r"deployment|디플로이먼트|배포\s*(리소스|상태|전략|오류|장애)|statefulset|daemonset|"
    r"operator|오퍼레이터|mco|machine\s*config|"
    r"lvmcluster|lvms|logical\s*volume\s*manager|storageclass|storage\s*class|"
    r"deviceselector|device\s*selector|(?<![a-z0-9])crd?(?![a-z0-9])|custom\s*resource|"
    r"스토리지\s*클래스|스토리지|볼륨|디바이스\s*셀렉터|장치\s*선택|커스텀\s*리소스|"
    r"pipeline|파이프라인|pipelines\s*as\s*code|pipelines-as-code|"
    r"\bpac\b|tekton|pipelinerun|taskrun|webhook|웹\s*훅|웹훅|"
    r"event|이벤트|log|로그|pending|"
    r"crashloopbackoff|notready|스케줄|스케줄링|"
    r"quota|쿼터|limitrange|limit\s*range|리밋|"
    r"rbac|authorization|권한|auth\s+can-i|can-i|"
    r"rolebinding|롤\s*바인딩|clusterrole|클러스터\s*롤|"
    r"csr|certificate|인증서|registry|레지스트리|monitoring|모니터링"
    r")",
    re.IGNORECASE,
)

DEFAULT_OPERATOR_CLI_QUALITY_SYSTEM_PROMPT = (
    "당신은 Red Hat OpenShift 운영자를 돕는 한국어 어시스턴트입니다. "
    "답변에는 내부 tool/function 이름(events_list, pods_log 등)을 절대 노출하지 말고, "
    "사용자가 바로 실행할 수 있는 oc/kubectl CLI 명령어를 제시하세요. "
    "문제 진단 답변은 순서, 명령어, 목적, 다음 판단 기준을 포함하세요. "
    "명령어는 인라인 코드가 아니라 ```bash fenced code block```으로 분리해서 보여주세요. "
    "코드블록 안에는 사용자가 복사해 실행할 명령어 하나만 넣고, 설명 주석은 코드블록 밖 문장으로 작성하세요. "
    "여러 명령어가 필요하면 설명 문장과 코드블록을 명령어별로 분리하세요. "
    "짧은 요약만 하지 말고 각 단계에서 무엇을 보고 다음에 어떻게 판단할지 설명하세요. "
    "이벤트와 로그를 설명할 때는 oc describe pod, oc get events, oc logs, "
    "oc logs --previous, oc logs -f, -n <namespace> 같은 실제 명령어를 우선 사용하세요."
)
OPERATOR_CLI_QUALITY_QUERY_SUFFIX = (
    "\n\n답변 형식 지침: 내부 tool/function 이름(events_list, pods_log 등)을 쓰지 말고 "
    "사용자가 실행할 실제 OpenShift CLI 명령어로 답하세요. "
    "명령어는 반드시 ```bash fenced code block```으로 분리하세요. "
    "코드블록 안에는 설명 주석 없이 복사 가능한 명령어 하나만 넣으세요. "
    "여러 명령어가 필요하면 명령어마다 설명 문장과 코드블록을 따로 나누세요. "
    "가능하면 oc describe pod, oc get events, oc logs, --previous, -f, -n <namespace>를 포함하세요. "
    "답변은 '1단계: 이벤트 확인', '2단계: 로그 확인', '요약 워크플로우' 흐름으로 작성하고, "
    "각 단계마다 명령어의 목적과 다음 판단 기준을 한두 문장으로 설명하세요."
)

INTERNAL_TOOL_NAME_RE = re.compile(
    r"\b(?:events_list|pods_log|pods_list|resources_get|namespaces_list|logs_get|cluster_status)\b",
    re.IGNORECASE,
)
CLI_COMMAND_RE = re.compile(r"\b(?:oc|kubectl)\s+[a-z][^\n`]*", re.IGNORECASE)


def evaluate_lightspeed_answer_quality(answer: str) -> dict[str, Any]:
    """Return lightweight quality signals without rewriting the Lightspeed answer."""

    text = str(answer or "")
    internal_tool_names = sorted({match.group(0) for match in INTERNAL_TOOL_NAME_RE.finditer(text)})
    cli_commands = sorted({match.group(0).strip() for match in CLI_COMMAND_RE.finditer(text)})
    return {
        "internal_tool_names": internal_tool_names,
        "internal_tool_name_count": len(internal_tool_names),
        "cli_command_count": len(cli_commands),
        "cli_command_samples": cli_commands[:5],
        "passes_operator_cli_quality": not internal_tool_names and len(cli_commands) >= 2,
    }


def _hash_prompt(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def normalize_lightspeed_query(query: str) -> str:
    """Normalize common Korean chat typos before sending a query to Lightspeed."""

    normalized = str(query or "").strip()
    if not normalized:
        return normalized
    normalized = re.sub(
        r"잇(?=(?:어|나|냐|니|는|을|으|습|고|지|죠|다|게|나요|습니까|으면))",
        "있",
        normalized,
    )
    return normalized


@dataclass(slots=True)
class OpenShiftLightspeedResult:
    answer: str
    conversation_id: str = ""
    referenced_documents: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    available_quotas: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    request_metadata: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OpenShiftLightspeedAuthResult:
    authorized: bool
    status_code: int
    detail: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class OpenShiftLightspeedApiError(RuntimeError):
    def __init__(self, *, status_code: int, detail: str) -> None:
        super().__init__(detail or f"OpenShift Lightspeed API returned HTTP {status_code}")
        self.status_code = status_code
        self.detail = detail


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _error_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return str(getattr(response, "text", "") or "").strip()[:500]
    if not isinstance(payload, dict):
        return ""
    detail = payload.get("detail")
    if isinstance(detail, dict):
        response_text = str(detail.get("response") or "").strip()
        cause_text = str(detail.get("cause") or "").strip()
        return " | ".join(part for part in [response_text, cause_text] if part)[:500]
    if isinstance(detail, list):
        parts: list[str] = []
        for item in detail:
            if not isinstance(item, dict):
                continue
            loc_value = item.get("loc")
            loc = ".".join(str(part) for part in loc_value) if isinstance(loc_value, list) else ""
            msg = str(item.get("msg") or "").strip()
            if loc and msg:
                parts.append(f"{loc}: {msg}")
            elif msg:
                parts.append(msg)
        return "; ".join(parts)[:500]
    if isinstance(detail, str):
        return detail.strip()[:500]
    response_text = str(payload.get("response") or payload.get("message") or "").strip()
    cause_text = str(payload.get("cause") or "").strip()
    return " | ".join(part for part in [response_text, cause_text] if part)[:500]


def is_openshift_operation_question(query: str) -> bool:
    return bool(OPENSHIFT_OPERATION_RE.search(normalize_lightspeed_query(query)))


class OpenShiftLightspeedClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.openshift_lightspeed_base_url.rstrip("/")
        self.api_token = settings.openshift_lightspeed_api_token
        self.provider = settings.openshift_lightspeed_provider
        self.model = settings.openshift_lightspeed_model
        self.system_prompt = settings.openshift_lightspeed_system_prompt
        self.request_profile = (
            settings.openshift_lightspeed_request_profile or "console_parity"
        ).strip().lower() or "console_parity"
        self.force_provider_model = bool(settings.openshift_lightspeed_force_provider_model)
        self.timeout_seconds = settings.openshift_lightspeed_timeout_seconds
        self.verify_tls: bool | str = settings.openshift_lightspeed_verify_tls
        if settings.openshift_lightspeed_verify_tls and settings.openshift_lightspeed_ca_bundle_path:
            self.verify_tls = settings.openshift_lightspeed_ca_bundle_path

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url)

    @property
    def query_url(self) -> str:
        if self.base_url.endswith("/v1/query"):
            return self.base_url
        return f"{self.base_url}/v1/query"

    @property
    def authorized_url(self) -> str:
        query_url = self.query_url
        if query_url.endswith("/v1/query"):
            return f"{query_url[:-len('/v1/query')]}/authorized"
        return f"{self.base_url}/authorized"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def _quality_system_prompt(self) -> str:
        return self.system_prompt or DEFAULT_OPERATOR_CLI_QUALITY_SYSTEM_PROMPT

    def build_query_payload(
        self,
        query: str,
        *,
        conversation_id: str = "",
        request_profile: str = "",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        normalized_query = normalize_lightspeed_query(query)
        payload: dict[str, Any] = {"query": normalized_query}
        if conversation_id:
            payload["conversation_id"] = conversation_id

        profile = (request_profile or self.request_profile).strip().lower()
        if profile not in {"console_parity", "operator_cli_quality", "legacy_configured"}:
            profile = "console_parity"

        include_provider_model = self.force_provider_model or profile == "legacy_configured"
        if include_provider_model:
            if self.provider:
                payload["provider"] = self.provider
            if self.model:
                payload["model"] = self.model

        if profile == "operator_cli_quality":
            payload["system_prompt"] = self._quality_system_prompt()
            payload["query"] = f"{normalized_query}{OPERATOR_CLI_QUALITY_QUERY_SUFFIX}"
        elif profile == "legacy_configured" and self.system_prompt:
            payload["system_prompt"] = self.system_prompt

        request_metadata = {
            "request_profile": profile,
            "payload_keys": sorted(payload.keys()),
            "query_augmented": payload["query"] != normalized_query,
            "provider_present": "provider" in payload,
            "model_present": "model" in payload,
            "system_prompt_present": "system_prompt" in payload,
            "system_prompt_hash": _hash_prompt(str(payload.get("system_prompt") or "")),
        }
        return payload, request_metadata

    def check_authorized(self) -> OpenShiftLightspeedAuthResult:
        if not self.is_configured:
            raise ValueError("OPENSHIFT_LIGHTSPEED_BASE_URL is not configured")

        response = requests.post(
            self.authorized_url,
            headers=self._headers(),
            timeout=self.timeout_seconds,
            verify=self.verify_tls,
        )
        detail = _error_detail(response)
        raw: dict[str, Any] = {}
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            raw = payload
        if response.status_code >= 400:
            return OpenShiftLightspeedAuthResult(
                authorized=False,
                status_code=int(response.status_code),
                detail=detail,
                raw=raw,
            )
        return OpenShiftLightspeedAuthResult(
            authorized=True,
            status_code=int(response.status_code),
            detail=detail,
            raw=raw,
        )

    def query(
        self,
        query: str,
        *,
        conversation_id: str = "",
        request_profile: str = "",
    ) -> OpenShiftLightspeedResult:
        if not self.is_configured:
            raise ValueError("OPENSHIFT_LIGHTSPEED_BASE_URL is not configured")

        payload, request_metadata = self.build_query_payload(
            query,
            conversation_id=conversation_id,
            request_profile=request_profile,
        )

        response = requests.post(
            self.query_url,
            json=payload,
            headers=self._headers(),
            timeout=self.timeout_seconds,
            verify=self.verify_tls,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise OpenShiftLightspeedApiError(
                status_code=int(getattr(response, "status_code", 0) or 0),
                detail=_error_detail(response),
            ) from exc
        data = response.json()
        if not isinstance(data, dict):
            data = {}
        answer = str(data.get("response") or data.get("answer") or "").strip()
        quality = evaluate_lightspeed_answer_quality(answer)
        quotas = data.get("available_quotas")
        if not isinstance(quotas, dict):
            quotas = {}
        return OpenShiftLightspeedResult(
            answer=answer,
            conversation_id=str(data.get("conversation_id") or "").strip(),
            referenced_documents=_dict_list(data.get("referenced_documents")),
            truncated=bool(data.get("truncated", False)),
            input_tokens=_optional_int(data.get("input_tokens")),
            output_tokens=_optional_int(data.get("output_tokens")),
            available_quotas=quotas,
            tool_calls=_dict_list(data.get("tool_calls")),
            tool_results=_dict_list(data.get("tool_results")),
            request_metadata=request_metadata,
            quality=quality,
            raw=data,
        )
