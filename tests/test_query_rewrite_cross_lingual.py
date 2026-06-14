from play_book_studio.retrieval.cross_lingual import cross_lingual_rewrite_terms
from play_book_studio.retrieval.query import normalize_query


def test_cross_lingual_rewrite_adds_technical_terms_without_replacing_query() -> None:
    query = "특정 Pod의 리소스 사용량 확인하는 법"

    terms = cross_lingual_rewrite_terms(query)
    normalized = normalize_query(query)

    assert "리소스" in normalized
    assert "resource usage" in terms
    assert "oc adm top pods" in normalized
    assert "CPU" in normalized
    assert "memory" in normalized


def test_deployment_yaml_rewrite_expands_manifest_terms() -> None:
    normalized = normalize_query("배포 yaml파일은 어케 작성하지")

    assert "배포" in normalized
    assert "deployment" in normalized.lower()
    assert "kind:" in normalized
    assert "oc apply -f" in normalized
