from play_book_studio.retrieval.book_adjustments import query_book_adjustments
from play_book_studio.retrieval.models import SessionContext
from play_book_studio.retrieval.query import normalize_query
from play_book_studio.retrieval.query_understanding import understand_query, understand_query_signals


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
    assert "configmap" in normalized.lower()
    assert "describe" in normalized
    assert "events" in normalized


def test_generic_setting_query_does_not_expand_to_secret_configmap() -> None:
    understanding = understand_query("Route HTTP header 설정 방법")
    normalized = normalize_query("Route HTTP header 설정 방법")

    assert "secret_config_concept" not in understanding.intents
    assert "secret_config_troubleshooting" not in understanding.intents
    assert "oc get secret" not in understanding.retrieval_terms
    assert "oc get configmap" not in understanding.retrieval_terms
    assert "Secret" not in normalized
    assert "ConfigMap" not in normalized
    assert "TLS" not in normalized
    assert "Ingress" not in normalized


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


def test_v012_beginner_intents_expand_operational_terms() -> None:
    deployment = understand_query("보통 배포 yaml파일은 어케 작성하지")
    service = understand_query("Service쪽에서 계속 장애나는데 뭐가 원인일까?")
    namespace = understand_query("특정 namespace를 만드는 명령어가 뭐야?")
    pod_usage = understand_query("특정 Pod의 리소스가 얼마나 잡아먹고 있는지 확인하는 법")

    assert "deployment_yaml_authoring" in deployment.intents
    assert "kind: Deployment" in deployment.retrieval_terms
    assert "oc apply -f" in deployment.retrieval_terms

    assert "service_failure_diagnosis" in service.intents
    assert "Endpoint" in service.retrieval_terms
    assert "oc get endpoints" in service.retrieval_terms

    assert "namespace_create" in namespace.intents
    assert "oc create namespace" in namespace.retrieval_terms

    assert "pod_resource_inspection" in pod_usage.intents
    assert "oc adm top pods" in pod_usage.retrieval_terms


def test_service_route_concept_question_does_not_become_failure_diagnosis() -> None:
    understanding = understand_query("Service와 Route 연결은 뭔지부터 알고 싶은데 어디서 확인하면 돼?")
    normalized = normalize_query("Service와 Route 연결은 뭔지부터 알고 싶은데 어디서 확인하면 돼?")

    assert "service_failure_diagnosis" not in understanding.intents
    assert understanding.answer_shape == "command_with_judgement"
    assert "oc describe service" not in normalized
    assert "oc get endpoints" not in normalized


def test_v014_query_signals_extract_pvc_pending_retrieval_contract() -> None:
    signals = understand_query_signals("PVC가 Pending인데 뭐 확인해야 해?")

    assert signals.classification["domain"] == "storage"
    assert signals.classification["book_slug_candidates"] == ("storage",)
    assert signals.search_signals["objects"] == ("PVC",)
    assert signals.search_signals["error_states"] == ("Pending",)
    assert "troubleshoot" in signals.search_signals["intent_labels"]
    assert "check_status" in signals.search_signals["intent_labels"]
    assert "checklist" in signals.search_signals["answer_shapes"]
    assert "command" in signals.search_signals["answer_shapes"]
    assert "oc_get" in signals.search_signals["command_families"]
    assert "oc_describe" in signals.search_signals["command_families"]
    assert {"key": "classification.domain", "match": {"value": "storage"}} in signals.metadata_filter["must"]
    assert "PVC Pending" in signals.vector_query
    assert "oc_describe" in signals.vector_query


def test_v014_query_signals_extract_etcd_execution_target_without_book_hard_filter() -> None:
    signals = understand_query_signals("etcd 백업은 어느 노드에서 실행해?")

    assert signals.classification["domain"] == "etcd"
    assert signals.classification["book_slug_candidates"] == ("etcd",)
    assert "backup" in signals.search_signals["intent_labels"]
    assert "identify_execution_target" in signals.search_signals["intent_labels"]
    assert signals.search_signals["execution_target"] == ("control_plane_node",)
    assert {"key": "classification.domain", "match": {"value": "etcd"}} in signals.metadata_filter["must"]
    assert not any(item["key"] == "classification.book_slug" for item in signals.metadata_filter["must"])


def test_v014_query_signals_extract_install_compare_shape() -> None:
    signals = understand_query_signals("UPI랑 agent-based 설치 차이 알려줘")

    assert signals.classification["domain"] == "install"
    assert "installing_on_any_platform" in signals.classification["book_slug_candidates"]
    assert "installation_overview" in signals.classification["book_slug_candidates"]
    assert "install" in signals.search_signals["intent_labels"]
    assert "compare_options" in signals.search_signals["intent_labels"]
    assert signals.search_signals["answer_shapes"] == ("decision_guide",)
    assert {"key": "classification.domain", "match": {"value": "install"}} in signals.metadata_filter["must"]
