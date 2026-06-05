"""OpenShift Lightspeed API client and routing helpers."""

from __future__ import annotations

import re
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
    r"event|이벤트|log|로그|pending|"
    r"crashloopbackoff|notready|스케줄|스케줄링|"
    r"quota|쿼터|limitrange|limit\s*range|리밋|"
    r"rbac|authorization|권한|auth\s+can-i|can-i|"
    r"rolebinding|롤\s*바인딩|clusterrole|클러스터\s*롤|"
    r"csr|certificate|인증서|registry|레지스트리|monitoring|모니터링"
    r")",
    re.IGNORECASE,
)


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
    return bool(OPENSHIFT_OPERATION_RE.search(str(query or "")))


class OpenShiftLightspeedClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.openshift_lightspeed_base_url.rstrip("/")
        self.api_token = settings.openshift_lightspeed_api_token
        self.provider = settings.openshift_lightspeed_provider
        self.model = settings.openshift_lightspeed_model
        self.system_prompt = settings.openshift_lightspeed_system_prompt
        self.timeout_seconds = settings.openshift_lightspeed_timeout_seconds
        self.verify_tls = settings.openshift_lightspeed_verify_tls

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
    ) -> OpenShiftLightspeedResult:
        if not self.is_configured:
            raise ValueError("OPENSHIFT_LIGHTSPEED_BASE_URL is not configured")

        payload: dict[str, Any] = {"query": query}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        if self.provider:
            payload["provider"] = self.provider
        if self.model:
            payload["model"] = self.model
        if self.system_prompt:
            payload["system_prompt"] = self.system_prompt

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
            raw=data,
        )
