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
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model
        self.temperature = settings.llm_temperature
        self.max_tokens = settings.llm_max_tokens
        self.timeout = max(settings.request_timeout_seconds, 120)
        self.preferred_provider = "openai-compatible"
        self.fallback_enabled = False
        self._last_generation_meta = {
            "preferred_provider": self.preferred_provider,
            "fallback_enabled": self.fallback_enabled,
            "last_provider": None,
            "last_fallback_used": False,
            "last_attempted_providers": [],
            "last_requested_max_tokens": self.max_tokens,
        }

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        if " " in self.api_key.strip():
            return {"Authorization": self.api_key.strip()}
        return {"Authorization": f"Bearer {self.api_key}"}

    def _post_openai(
        self,
        messages: list[dict[str, str]],
        *,
        include_reasoning_controls: bool,
        max_tokens: int | None = None,
    ) -> requests.Response:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
        }
        if include_reasoning_controls:
            payload["reasoning"] = False
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        return requests.post(
            f"{self.endpoint}/chat/completions",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )

    def _parse_openai_payload(self, payload: dict) -> str:
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
            return content.strip()
        raise ValueError("LLM response is missing message content")

    def _generate_openai(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
    ) -> str:
        response = self._post_openai(
            messages,
            include_reasoning_controls=True,
            max_tokens=max_tokens,
        )
        if response.status_code == 400:
            response_text = response.text.lower()
            if "reasoning" in response_text or "chat_template_kwargs" in response_text:
                response = self._post_openai(
                    messages,
                    include_reasoning_controls=False,
                    max_tokens=max_tokens,
                )
        response.raise_for_status()
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ValueError("LLM response is not valid JSON") from exc
        return self._parse_openai_payload(payload)

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
            content = self._generate_openai(messages, max_tokens=requested_max_tokens)
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
            }
            raise

    def runtime_metadata(self) -> dict[str, object]:
        return {
            "preferred_provider": self.preferred_provider,
            "fallback_enabled": self.fallback_enabled,
            **self._last_generation_meta,
        }
