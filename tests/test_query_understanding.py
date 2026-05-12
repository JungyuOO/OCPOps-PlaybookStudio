from play_book_studio.retrieval.book_adjustments import query_book_adjustments
from play_book_studio.retrieval.models import SessionContext
from play_book_studio.retrieval.query import normalize_query
from play_book_studio.retrieval.query_understanding import understand_query


def test_ocp_install_query_expands_to_openshift_installation_terms() -> None:
    normalized = normalize_query("OCP 설치 어떻게 해")

    assert "OpenShift Container Platform" in normalized
    assert "설치" in normalized
    assert "개요" in normalized
    assert "Assisted Installer" in normalized
    assert "Agent-based" in normalized
    assert "Single Node" in normalized


def test_openshift_install_query_boosts_installation_books() -> None:
    boosts, penalties = query_book_adjustments(
        "OCP 설치 어떻게 해 OpenShift Container Platform 설치 개요",
        context=SessionContext(),
    )

    assert boosts["installation_overview"] >= 2.0
    assert boosts["install_modes"] >= 1.5
    assert boosts["installing_on_any_platform"] >= 1.5
    assert penalties["release_notes"] < 1.0


def test_secret_config_error_query_understanding_expands_for_troubleshooting() -> None:
    understanding = understand_query("Secret config error keeps happening")
    normalized = normalize_query("Secret config error keeps happening")

    assert "troubleshooting" in understanding.intents
    assert "secret_config_troubleshooting" in understanding.intents
    assert understanding.answer_shape == "troubleshooting_steps"
    assert "oc describe secret" in understanding.retrieval_terms
    assert "Secret" in normalized
    assert "ConfigMap" in normalized
    assert "describe" in normalized
    assert "events" in normalized


def test_namespace_command_query_understanding_expands_project_commands() -> None:
    understanding = understand_query("namespace check command")
    normalized = normalize_query("namespace check command")

    assert "command_lookup" in understanding.intents
    assert "namespace_or_project" in understanding.intents
    assert understanding.answer_shape == "command_with_judgement"
    assert "oc get namespaces" in understanding.retrieval_terms
    assert "oc get projects" in understanding.retrieval_terms
    assert "namespaces" in normalized
    assert "projects" in normalized
