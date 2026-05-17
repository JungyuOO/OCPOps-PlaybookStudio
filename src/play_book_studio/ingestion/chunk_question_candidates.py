"""Generate starter/follow-up question candidates from chunk content.

Question candidates are authored once during ingestion. Runtime starter
question code should consume the stored candidates and only use copy fallback
when the database has none.
"""

from __future__ import annotations

import json
import re
from typing import Any


SPACE_RE = re.compile(r"\s+")
COMMAND_RE = re.compile(r"\b(?:oc|kubectl|openshift-install|etcdctl)\s+[^\n`]+", re.IGNORECASE)
INTERNAL_CHUNK_KIND_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)*(?:_detail|_summary)\b", re.IGNORECASE)
INTERNAL_QUESTION_RE = re.compile(
    r"\bchunk(?:_kind)?|청크|"
    r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)*(?:_detail|_summary)\b",
    re.IGNORECASE,
)


SYSTEM_PROMPT = """너는 OpenShift 공식 문서 청크를 보고 채팅 첫 화면에 보여줄 한국어 질문을 만드는 편집자다.
청크에 실제로 있는 내용만 바탕으로, 자연스럽고 사용자가 바로 누를 수 있는 질문을 만든다.
템플릿처럼 어색한 조사 조합을 만들지 말고, 사람이 ChatGPT에 묻는 문장처럼 쓴다.
JSON만 반환한다."""


def build_chunk_question_candidates(chunk: dict[str, Any], *, llm_client: Any | None = None) -> dict[str, list[str]]:
    if has_current_question_candidates(chunk):
        return {
            "starter_question_candidates": _clean_questions(chunk.get("starter_question_candidates"), limit=3),
            "followup_question_candidates": _clean_questions(chunk.get("followup_question_candidates"), limit=4),
        }
    if llm_client is None:
        return {"starter_question_candidates": [], "followup_question_candidates": []}

    payload = _chunk_prompt_payload(chunk)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "다음 청크를 바탕으로 자연스러운 한국어 시작 질문 2~3개와 후속 질문 1~4개를 만들어라.\n"
                "출력 형식은 반드시 JSON 객체 하나다:\n"
                '{"starter_question_candidates":["..."],"followup_question_candidates":["..."]}\n\n'
                f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
            ),
        },
    ]
    try:
        raw = llm_client.generate(messages, max_tokens=420)
    except TypeError:
        try:
            raw = llm_client.generate(messages)
        except Exception:  # noqa: BLE001
            return {"starter_question_candidates": [], "followup_question_candidates": []}
    except Exception:  # noqa: BLE001
        return {"starter_question_candidates": [], "followup_question_candidates": []}
    return _parse_candidate_response(raw)


def _chunk_prompt_payload(chunk: dict[str, Any]) -> dict[str, Any]:
    text = _clean_text(str(chunk.get("text") or chunk.get("markdown") or chunk.get("embedding_text") or ""))
    return {
        "heading_title": _clean_text(
            str(chunk.get("heading_title") or chunk.get("heading") or chunk.get("section") or chunk.get("chapter") or "")
        ),
        "section_path": _string_list(chunk.get("section_path") or chunk.get("section_path_label") or ()),
        "text_excerpt": text[:1200],
        "cli_commands": _commands(chunk, text)[:8],
        "k8s_objects": _string_list(chunk.get("k8s_objects"))[:8],
    }


def has_current_question_candidates(chunk: dict[str, Any]) -> bool:
    try:
        version = int(chunk.get("question_candidates_version") or 0)
    except (TypeError, ValueError):
        version = 0
    return version >= 2 and bool(_clean_questions(chunk.get("starter_question_candidates"), limit=1))


def _parse_candidate_response(raw: str) -> dict[str, list[str]]:
    data = _json_object(raw)
    starters = _clean_questions(data.get("starter_question_candidates"), limit=3)
    followups = _clean_questions(data.get("followup_question_candidates"), limit=4)
    return {
        "starter_question_candidates": starters,
        "followup_question_candidates": followups,
    }


def _json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _clean_questions(values: Any, *, limit: int) -> list[str]:
    if not isinstance(values, list | tuple):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        question = SPACE_RE.sub(" ", str(value or "").strip())
        if INTERNAL_QUESTION_RE.search(question):
            continue
        if not question or "�" in question:
            continue
        if not question.endswith("?"):
            question = f"{question}?"
        key = question.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(question)
        if len(result) >= limit:
            break
    return result


def _clean_text(value: str) -> str:
    lines: list[str] = []
    for line in str(value or "").splitlines():
        cleaned = SPACE_RE.sub(" ", line).strip()
        if not cleaned:
            continue
        if INTERNAL_CHUNK_KIND_RE.search(cleaned) and ("청크" in cleaned or "chunk" in cleaned.lower()):
            continue
        lines.append(cleaned)
    return SPACE_RE.sub(" ", " ".join(lines)).strip()


def _commands(chunk: dict[str, Any], text: str) -> list[str]:
    raw_values = chunk.get("cli_commands")
    commands = _string_list(raw_values)
    commands.extend(match.group(0).strip() for match in COMMAND_RE.finditer(text))
    return _dedupe(commands)


def _string_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [values] if values.strip() else []
    try:
        return [str(item or "").strip() for item in values if str(item or "").strip()]
    except TypeError:
        value = str(values or "").strip()
        return [value] if value else []


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = SPACE_RE.sub(" ", str(value or "").strip())
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


__all__ = ["build_chunk_question_candidates", "has_current_question_candidates"]
