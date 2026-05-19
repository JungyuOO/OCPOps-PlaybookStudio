# LLM 서버 호출, provider fallback, 응답 파싱을 담당하는 어댑터.
from __future__ import annotations

import json
import time

import requests

from play_book_studio.config.settings import Settings


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.llm_endpoint:
            raise ValueError("LLM_ENDPOINT must be configured")
        if not settings.llm_model:
            raise ValueError("LLM_MODEL must be configured")
        self.endpoint = settings.llm_endpoint
        self.model = settings.llm_model
        self.temperature = settings.llm_temperature
        self.max_tokens = settings.llm_max_tokens
        self.timeout = max(settings.request_timeout_seconds, 120)
        self.preferred_provider = "openai-compatible"
        self.fallback_enabled = False
        self._last_http_debug: dict[str, object] = {}
        self._last_generation_meta = {
            "preferred_provider": self.preferred_provider,
            "fallback_enabled": self.fallback_enabled,
            "last_provider": None,
            "last_fallback_used": False,
            "last_attempted_providers": [],
            "last_requested_max_tokens": self.max_tokens,
            "last_http_debug": {},
        }

    def _emit_http_trace(self, trace_callback, *, label: str, status: str, meta: dict) -> None:
        if trace_callback is None:
            return
        trace_callback(
            {
                "type": "trace",
                "step": "llm_http",
                "label": label,
                "status": status,
                "meta": meta,
            }
        )

    def _post_openai(
        self,
        messages: list[dict[str, str]],
        *,
        include_reasoning_controls: bool,
        max_tokens: int | None = None,
        trace_callback=None,
        attempt_index: int = 1,
        call_started_at: float | None = None,
    ) -> requests.Response:
        call_started_at = call_started_at if call_started_at is not None else time.perf_counter()
        attempt_started_at = time.perf_counter()
        payload_started_at = time.perf_counter()
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
        }
        if include_reasoning_controls:
            payload["reasoning"] = False
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        request_payload_flags = {
            key: payload[key]
            for key in ("reasoning", "chat_template_kwargs")
            if key in payload
        }
        payload_build_ms = round((time.perf_counter() - payload_started_at) * 1000, 1)
        request_started_at = time.perf_counter()
        self._emit_http_trace(
            trace_callback,
            label="LLM HTTP 요청 시작",
            status="running",
            meta={
                "attempt": attempt_index,
                "provider": "openai-compatible",
                "endpoint": f"{self.endpoint}/chat/completions",
                "model": self.model,
                "message_count": len(messages),
                "prompt_chars": sum(len(str(message.get("content") or "")) for message in messages),
                "max_tokens": payload["max_tokens"],
                "include_reasoning_controls": include_reasoning_controls,
                "request_payload_flags": request_payload_flags,
                "payload_build_ms": payload_build_ms,
                "elapsed_since_call_start_ms": round((request_started_at - call_started_at) * 1000, 1),
            },
        )
        response = requests.post(
            f"{self.endpoint}/chat/completions",
            json=payload,
            headers={},
            timeout=self.timeout,
            stream=True,
        )
        headers_received_at = time.perf_counter()
        response._pbs_llm_debug = {  # type: ignore[attr-defined]
            "attempt": attempt_index,
            "provider": "openai-compatible",
            "endpoint": f"{self.endpoint}/chat/completions",
            "model": self.model,
            "message_count": len(messages),
            "prompt_chars": sum(len(str(message.get("content") or "")) for message in messages),
            "max_tokens": payload["max_tokens"],
            "include_reasoning_controls": include_reasoning_controls,
            "request_payload_flags": request_payload_flags,
            "payload_build_ms": payload_build_ms,
            "http_headers_ms": round((headers_received_at - request_started_at) * 1000, 1),
            "attempt_elapsed_ms": round((headers_received_at - attempt_started_at) * 1000, 1),
            "elapsed_since_call_start_ms": round((headers_received_at - call_started_at) * 1000, 1),
            "status_code": response.status_code,
            "response_headers": {
                key: value
                for key, value in response.headers.items()
                if key.lower() in {"content-type", "content-length", "date", "server", "x-request-id"}
            },
        }
        self._emit_http_trace(
            trace_callback,
            label="LLM HTTP 응답 헤더 수신",
            status="done",
            meta=response._pbs_llm_debug,  # type: ignore[attr-defined]
        )
        return response

    def _parse_openai_payload(self, payload: dict, *, debug: dict | None = None) -> str:
        extract_started_at = time.perf_counter()
        choices = payload.get("choices") or []
        if not choices:
            raise ValueError("LLM response is missing choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            content = "\n".join(parts).strip()
        if isinstance(content, str) and content.strip():
            if debug is not None:
                debug["content_extract_ms"] = round((time.perf_counter() - extract_started_at) * 1000, 1)
                debug["raw_output_chars"] = len(content)
                usage = payload.get("usage")
                if isinstance(usage, dict):
                    debug["usage"] = usage
            return content.strip()
        raise ValueError("LLM response is missing message content")

    def _read_openai_json(self, response: requests.Response, *, debug: dict) -> dict:
        body_started_at = time.perf_counter()
        body = response.content
        debug["body_read_ms"] = round((time.perf_counter() - body_started_at) * 1000, 1)
        debug["body_bytes"] = len(body)
        parse_started_at = time.perf_counter()
        try:
            payload = json.loads(body.decode(response.encoding or "utf-8"))
        except json.JSONDecodeError as exc:
            debug["json_parse_ms"] = round((time.perf_counter() - parse_started_at) * 1000, 1)
            raise ValueError("LLM response is not valid JSON") from exc
        debug["json_parse_ms"] = round((time.perf_counter() - parse_started_at) * 1000, 1)
        return payload

    def _generate_openai(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        trace_callback=None,
    ) -> str:
        call_started_at = time.perf_counter()
        attempts_debug: list[dict] = []
        response = self._post_openai(
            messages,
            include_reasoning_controls=True,
            max_tokens=max_tokens,
            trace_callback=trace_callback,
            attempt_index=1,
            call_started_at=call_started_at,
        )
        first_debug = dict(getattr(response, "_pbs_llm_debug", {}) or {})
        if response.status_code == 400:
            body_started_at = time.perf_counter()
            response_text = response.text.lower()
            first_debug["body_read_ms"] = round((time.perf_counter() - body_started_at) * 1000, 1)
            first_debug["body_bytes"] = len(response.content)
            first_debug["fallback_triggered"] = "reasoning" in response_text or "chat_template_kwargs" in response_text
            attempts_debug.append(first_debug)
            response_text = response.text.lower()
            if "reasoning" in response_text or "chat_template_kwargs" in response_text:
                response = self._post_openai(
                    messages,
                    include_reasoning_controls=False,
                    max_tokens=max_tokens,
                    trace_callback=trace_callback,
                    attempt_index=2,
                    call_started_at=call_started_at,
                )
        else:
            attempts_debug.append(first_debug)
        active_debug = dict(getattr(response, "_pbs_llm_debug", {}) or first_debug)
        response.raise_for_status()
        payload = self._read_openai_json(response, debug=active_debug)
        content = self._parse_openai_payload(payload, debug=active_debug)
        active_debug["total_call_ms"] = round((time.perf_counter() - call_started_at) * 1000, 1)
        if not attempts_debug or attempts_debug[-1].get("attempt") != active_debug.get("attempt"):
            attempts_debug.append(active_debug)
        else:
            attempts_debug[-1] = active_debug
        self._last_http_debug = {
            "attempt_count": len(attempts_debug),
            "attempts": attempts_debug,
            "total_call_ms": active_debug["total_call_ms"],
        }
        self._emit_http_trace(
            trace_callback,
            label="LLM HTTP 본문/JSON 처리 완료",
            status="done",
            meta=self._last_http_debug,
        )
        return content

    def generate(
        self,
        messages: list[dict[str, str]],
        trace_callback=None,
        *,
        max_tokens: int | None = None,
    ) -> str:
        requested_max_tokens = max_tokens if max_tokens is not None else self.max_tokens

        def emit(
            *,
            step: str,
            label: str,
            status: str,
            detail: str = "",
            duration_ms: float | None = None,
            meta: dict | None = None,
        ) -> None:
            if trace_callback is None:
                return
            event = {
                "type": "trace",
                "step": step,
                "label": label,
                "status": status,
            }
            if detail:
                event["detail"] = detail
            if duration_ms is not None:
                event["duration_ms"] = round(duration_ms, 1)
            if meta:
                event["meta"] = meta
            trace_callback(event)

        def generate_openai() -> str:
            openai_started_at = time.perf_counter()
            emit(
                step="llm_generate",
                label="LLM 응답 생성 중",
                status="running",
                detail=(
                    f"provider=openai-compatible model={self.model} "
                    f"max_tokens={requested_max_tokens}"
                ),
            )
            content = self._generate_openai(
                messages,
                max_tokens=requested_max_tokens,
                trace_callback=trace_callback,
            )
            emit(
                step="llm_generate",
                label="LLM 응답 생성 완료",
                status="done",
                detail=(
                    f"provider=openai-compatible model={self.model} "
                    f"max_tokens={requested_max_tokens}"
                ),
                duration_ms=(time.perf_counter() - openai_started_at) * 1000,
                meta={
                    "provider": "openai-compatible",
                    "model": self.model,
                    "requested_max_tokens": requested_max_tokens,
                    "http_debug": getattr(self, "_last_http_debug", {}),
                },
            )
            return content

        attempted_providers = ["openai-compatible"]
        try:
            content = generate_openai()
            self._last_generation_meta = {
                "preferred_provider": self.preferred_provider,
                "fallback_enabled": self.fallback_enabled,
                "last_provider": "openai-compatible",
                "last_fallback_used": False,
                "last_attempted_providers": attempted_providers,
                "last_requested_max_tokens": requested_max_tokens,
                "last_http_debug": getattr(self, "_last_http_debug", {}),
            }
            return content
        except Exception:
            self._last_generation_meta = {
                "preferred_provider": self.preferred_provider,
                "fallback_enabled": self.fallback_enabled,
                "last_provider": None,
                "last_fallback_used": False,
                "last_attempted_providers": attempted_providers,
                "last_requested_max_tokens": requested_max_tokens,
                "last_http_debug": getattr(self, "_last_http_debug", {}),
            }
            raise

    def runtime_metadata(self) -> dict[str, object]:
        return {
            "preferred_provider": self.preferred_provider,
            "fallback_enabled": self.fallback_enabled,
            **self._last_generation_meta,
        }
