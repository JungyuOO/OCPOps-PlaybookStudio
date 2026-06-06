from play_book_studio.retrieval.book_adjustments import query_book_adjustments
from play_book_studio.retrieval.models import RetrievalHit, SessionContext
from play_book_studio.retrieval.query import normalize_query
from play_book_studio.retrieval.scoring import fuse_ranked_hits
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


def test_official_book_adjustments_prioritize_network_policy_books() -> None:
    boosts, penalties = query_book_adjustments(
        "OpenShift 네트워크 정책과 pod 통신 제한을 확인하고 싶어",
        context=SessionContext(),
    )

    assert boosts["advanced_networking"] >= 1.5
    assert boosts["networking_overview"] >= 1.3
    assert penalties["security_and_compliance"] < 0.8


def test_official_book_adjustments_prioritize_image_pull_books() -> None:
    boosts, penalties = query_book_adjustments(
        "ImagePullBackOff가 날 때 이미지 레지스트리와 pull secret 확인 기준은?",
        context=SessionContext(),
    )

    assert boosts["images"] >= 1.7
    assert boosts["registry"] >= 1.3
    assert penalties["disconnected_environments"] < 0.8
    assert penalties["installation_overview"] < 0.8


def test_official_book_adjustments_prioritize_node_drain_aliases() -> None:
    boosts, penalties = query_book_adjustments(
        "워커 노드를 드레이닝하려면 뭘 봐야 해?",
        context=SessionContext(),
    )

    assert boosts["nodes"] >= 1.6
    assert boosts["cli_tools"] >= 1.1
    assert penalties["support"] < 1.0


def test_official_book_adjustments_prioritize_console_locator_books() -> None:
    boosts, penalties = query_book_adjustments(
        "OpenShift 콘솔에서 프로젝트와 워크로드를 확인하는 문서를 찾아줘",
        context=SessionContext(),
    )

    assert boosts["web_console"] >= 1.7
    assert penalties["support"] < 0.8
    assert penalties["nodes"] < 1.0


def test_official_book_adjustments_keep_pod_pending_out_of_cli_reference() -> None:
    boosts, penalties = query_book_adjustments(
        "Pod가 Pending이면 이벤트와 스케줄링 문제를 어떤 순서로 확인해야 해?",
        context=SessionContext(),
    )

    assert boosts["support"] >= 1.4
    assert boosts["nodes"] >= 1.2
    assert penalties["cli_tools"] < 0.8


def test_official_book_adjustments_keep_logging_out_of_audit_security() -> None:
    boosts, penalties = query_book_adjustments(
        "로그는 어디서 봐?",
        context=SessionContext(),
    )

    assert boosts["logging"] >= 2.5
    assert boosts["observability_overview"] >= 1.3
    assert penalties["cli_tools"] < 0.7
    assert penalties["nodes"] < 0.7
    assert penalties["security_and_compliance"] < 0.6


def test_official_book_adjustments_prioritize_concept_and_locator_books() -> None:
    control_plane_boosts, control_plane_penalties = query_book_adjustments(
        "컨트롤 플레인 구성 요소와 etcd 역할을 설명하는 문서가 필요해",
        context=SessionContext(),
    )
    backup_boosts, backup_penalties = query_book_adjustments(
        "클러스터 백업과 복구 관련 문서 위치를 알려줘",
        context=SessionContext(),
    )

    assert control_plane_boosts["architecture"] >= 1.7
    assert control_plane_boosts["etcd"] >= 1.2
    assert control_plane_penalties["backup_and_restore"] < 0.8
    assert backup_boosts["backup_and_restore"] >= 1.8
    assert backup_boosts["etcd"] >= 1.3
    assert backup_penalties["postinstallation_configuration"] < 1.0


def test_official_book_adjustments_rebalance_project_namespace_compare() -> None:
    boosts, penalties = query_book_adjustments(
        "OpenShift project와 namespace 차이를 설명하는 공식 문서가 필요해",
        context=SessionContext(),
    )

    assert boosts["overview"] >= 1.4
    assert boosts.get("cli_tools", 1.0) == 1.0
    assert penalties["machine_management"] < 0.6
    assert penalties["security_and_compliance"] < 0.6
    assert penalties["postinstallation_configuration"] < 0.8


def test_project_namespace_compare_penalizes_irrelevant_cli_sections() -> None:
    irrelevant_cli = RetrievalHit(
        chunk_id="cli-odo-release",
        book_slug="cli_tools",
        chapter="CLI",
        section="4장. odo에서 중요한 업데이트",
        anchor="oc-adm-release-new",
        source_url="",
        viewer_path="/playbooks/wiki-runtime/active/cli_tools/index.html#oc-adm-release-new",
        text="Use oc adm release new to create a release payload.",
        source="bm25",
        raw_score=1.0,
    )
    overview = RetrievalHit(
        chunk_id="overview-project-namespace",
        book_slug="overview",
        chapter="Overview",
        section="OpenShift Container Platform의 일반 용어집",
        anchor="project-namespace",
        source_url="",
        viewer_path="/playbooks/wiki-runtime/active/overview/index.html#project-namespace",
        text="OpenShift projects provide Kubernetes namespace scoping for applications.",
        source="bm25",
        raw_score=0.8,
    )

    hits = fuse_ranked_hits(
        "OpenShift project와 namespace 차이를 설명하는 공식 문서가 필요해",
        {"bm25": [irrelevant_cli, overview], "vector": [irrelevant_cli, overview]},
        context=SessionContext(),
        top_k=2,
    )

    assert hits[0].chunk_id == "overview-project-namespace"
    assert hits[1].component_scores["project_namespace_cli_section_mismatch_penalty"] == 0.34


def test_official_book_adjustments_route_external_exposure_without_registry_context() -> None:
    boosts, penalties = query_book_adjustments(
        "그럼 외부로 공개할 땐 뭘 봐야 해?",
        context=SessionContext(),
    )

    assert boosts["ingress_and_load_balancing"] >= 1.8
    assert boosts["networking_overview"] >= 1.3
    assert penalties["registry"] < 0.6


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


def test_korean_project_list_query_prioritizes_get_commands_not_create() -> None:
    understanding = understand_query("전체 프로젝트 목록 확인 어떻게 해")
    normalized = normalize_query("전체 프로젝트 목록 확인 어떻게 해")

    assert "command_lookup" in understanding.intents
    assert "namespace_or_project" in understanding.intents
    assert all(token in normalized for token in ("oc", "get", "projects", "namespaces"))
    assert "oc new-project" not in normalized
    assert "oc create namespace" not in normalized


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
    query = "Service와 Route 연결 구조를 먼저 이해하고 싶은데, 어디를 보면 될까요?"
    understanding = understand_query(query)
    normalized = normalize_query(query)

    assert "service_failure_diagnosis" not in understanding.intents
    assert understanding.answer_shape == "grounded_explanation"
    assert "oc describe service" not in normalized
    assert "oc get endpoints" not in normalized
    assert "relationship" in normalized
    assert "Networking" in normalized
    assert "overview" in normalized


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


def test_query_signals_extract_korean_static_provisioning_storage_contract() -> None:
    signals = understand_query_signals("정적 프로비저닝 기준으로 다음 확인 단계는 뭐야?")

    assert signals.classification["domain"] == "storage"
    assert signals.classification["book_slug_candidates"] == ("storage",)
    assert "PV" in signals.search_signals["objects"]
    assert "PVC" in signals.search_signals["objects"]
    assert "StorageClass" in signals.search_signals["objects"]
    assert "static provisioning" in signals.search_signals["primary_topics"]
    assert "check_status" in signals.search_signals["intent_labels"]
    assert {"key": "classification.domain", "match": {"value": "storage"}} in signals.metadata_filter["must"]
    assert "static provisioning" in signals.vector_query
    assert "PersistentVolumeClaim" in signals.vector_query


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
