"""Entity graph 기반 고객 환경값 공급자.

답변 시점에 citation 발췌문 regex(_extract_customer_context_values)가 놓친 고객
환경값을 graph_entity_* 테이블에서 구조적으로 보충한다. regex 값이 항상 우선하고,
graph는 비어 있는 키만 채운다. 실패 시 빈 결과를 반환해 답변 흐름을 막지 않는다.
"""

from __future__ import annotations

from typing import Any

from play_book_studio.db import graph_repository
from play_book_studio.db.graph_repository import GraphScopeFilter
from play_book_studio.graph.rules import query_name_tokens

_PIPELINE_ALIAS_TOKENS = ("ci/cd", "ci-cd", "pipeline", "파이프라인")
_CONTROLLER_ALIAS_TOKENS = ("controller", "컨트롤러")
_CONTROLLER_DEPLOYMENT_TOKEN = "pipelines-as-code"
_SMEE_URL_PREFIX = "https://smee.io/"


def _alias_text(entity: dict[str, Any]) -> str:
    aliases = entity.get("aliases")
    if not isinstance(aliases, (list, tuple)):
        return ""
    return " ".join(str(alias) for alias in aliases).casefold()


def load_graph_customer_context_values(
    settings,
    *,
    query: str,
    chunk_ids: list[str],
    answer_text: str = "",
    owner_user_id: str = "",
) -> dict[str, Any]:
    empty: dict[str, Any] = {"values": {}, "evidence": []}
    if not bool(getattr(settings, "entity_graph_enabled", False)):
        return empty
    database_url = str(getattr(settings, "database_url", "") or "").strip()
    if not database_url:
        return empty
    if not chunk_ids and not query.strip():
        return empty
    try:
        return _load(
            database_url,
            query=query,
            chunk_ids=[str(chunk_id) for chunk_id in chunk_ids if str(chunk_id).strip()],
            answer_text=answer_text,
            owner_user_id=owner_user_id,
        )
    except Exception:  # noqa: BLE001 - graph augmentation must never break answering
        return empty


def _load(
    database_url: str,
    *,
    query: str,
    chunk_ids: list[str],
    answer_text: str,
    owner_user_id: str,
) -> dict[str, Any]:
    import psycopg

    scope = GraphScopeFilter(owner_user_id=owner_user_id)
    # 인용 chunk에 entity가 없어도(예: 질문 헤딩만 있는 Q&A chunk) 질문/답변 본문에
    # 등장한 구체 이름(ci-pipelines 등)으로 graph entity를 찾을 수 있게 시드를 합친다.
    name_tokens = list(query_name_tokens(f"{query}\n{answer_text}"))
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            entities_by_id: dict[str, dict[str, Any]] = {}
            for row in graph_repository.find_entities_for_chunks(
                cursor, chunk_ids, scope=scope
            ):
                entities_by_id.setdefault(str(row["entity_id"]), row)
            for row in graph_repository.find_entities_by_names(
                cursor, name_tokens, scope=scope
            ):
                entities_by_id.setdefault(str(row["entity_id"]), row)
            if not entities_by_id:
                return {"values": {}, "evidence": []}
            relations = graph_repository.expand_relations(
                cursor,
                list(entities_by_id),
                scope=scope,
                limit=40,
            )

    values: dict[str, Any] = {}
    evidence: list[dict[str, str]] = []

    def adopt(key: str, value: str, *, entity_key: str, quote: str = "") -> None:
        if not value or key in values:
            return
        values[key] = value
        evidence.append({"key": key, "entity_key": entity_key, "quote": quote[:300]})

    entity_rows = list(entities_by_id.values())

    for entity in entity_rows:
        if str(entity.get("entity_kind")) == "repository_cr":
            adopt(
                "repository_name",
                str(entity.get("name") or ""),
                entity_key=str(entity.get("entity_key") or ""),
            )
            break

    for relation in relations:
        relation_type = str(relation.get("relation_type") or "")
        if relation_type != "in_namespace":
            continue
        subject_kind = str(relation.get("subject_kind") or "")
        subject_name = str(relation.get("subject_name") or "")
        object_name = str(relation.get("object_name") or "")
        quote = str(relation.get("quote") or "")
        if subject_kind == "repository_cr":
            adopt(
                "repository_namespace",
                object_name,
                entity_key=str(relation.get("object_key") or ""),
                quote=quote,
            )
            if not values.get("repository_name"):
                adopt(
                    "repository_name",
                    subject_name,
                    entity_key=str(relation.get("subject_key") or ""),
                    quote=quote,
                )
        if subject_kind == "deployment" and _CONTROLLER_DEPLOYMENT_TOKEN in subject_name:
            adopt(
                "controller_namespace",
                object_name,
                entity_key=str(relation.get("object_key") or ""),
                quote=quote,
            )
        if subject_kind in {"pipelinerun"}:
            adopt(
                "pipeline_namespace",
                object_name,
                entity_key=str(relation.get("object_key") or ""),
                quote=quote,
            )

    for entity in entity_rows:
        if str(entity.get("entity_kind")) != "namespace":
            continue
        alias_text = _alias_text(entity)
        if not alias_text:
            continue
        entity_key = str(entity.get("entity_key") or "")
        name = str(entity.get("name") or "")
        if any(token in alias_text for token in _PIPELINE_ALIAS_TOKENS):
            adopt("pipeline_namespace", name, entity_key=entity_key)
        if any(token in alias_text for token in _CONTROLLER_ALIAS_TOKENS):
            adopt("controller_namespace", name, entity_key=entity_key)

    for entity in entity_rows:
        if str(entity.get("entity_kind")) == "webhook_url" and str(
            entity.get("name") or ""
        ).startswith(_SMEE_URL_PREFIX):
            adopt(
                "smee_url",
                str(entity.get("name") or ""),
                entity_key=str(entity.get("entity_key") or ""),
            )
            break

    if not values.get("pipeline_namespace") and values.get("repository_namespace"):
        adopt(
            "pipeline_namespace",
            str(values["repository_namespace"]),
            entity_key="namespace:" + str(values["repository_namespace"]),
        )
    if not values.get("repository_namespace") and values.get("pipeline_namespace"):
        adopt(
            "repository_namespace",
            str(values["pipeline_namespace"]),
            entity_key="namespace:" + str(values["pipeline_namespace"]),
        )

    return {"values": values, "evidence": evidence}
