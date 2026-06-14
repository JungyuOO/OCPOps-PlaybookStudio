from pathlib import Path

from play_book_studio.retrieval.concept_expansion import expand_query_terms, load_concept_synonyms
from play_book_studio.retrieval.query import normalize_query


def test_concept_synonym_manifest_loads_core_entries() -> None:
    entries = load_concept_synonyms()

    assert len(entries) >= 25
    assert any(entry.get("concept_id") == "ocp:resource:Service" for entry in entries)
    assert any(entry.get("concept_id") == "ocp:resource:Deployment" for entry in entries)


def test_concept_synonym_expansion_appends_adjacent_terms() -> None:
    terms = expand_query_terms("Service쪽에서 계속 장애나는데 뭐가 원인일까?")

    assert "Endpoint" in terms
    assert "Route" in terms
    assert "oc describe service" in terms


def test_concept_synonym_expansion_dedupes_and_supports_custom_path(tmp_path: Path) -> None:
    path = tmp_path / "concepts.json"
    path.write_text(
        """
        {
          "concepts": [
            {
              "concept_id": "unit:service",
              "display_name_ko": "Service / 서비스",
              "synonyms": ["svc", "서비스"],
              "adjacent_terms": ["Endpoint", "Endpoint", "Route"]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    terms = expand_query_terms("svc 장애", path=str(path))

    assert terms == ["Endpoint", "Route", "Service / 서비스"]


def test_concept_synonym_expansion_flows_into_normalized_query() -> None:
    normalized = normalize_query("Service쪽 장애 원인")

    assert "Endpoint" in normalized
    assert "route" in normalized.lower()
    assert "selector" in normalized


def test_concept_synonym_expansion_returns_empty_for_unknown_query() -> None:
    assert expand_query_terms("아무 관련 없는 질문") == []
