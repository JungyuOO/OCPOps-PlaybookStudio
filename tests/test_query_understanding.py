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


def test_file_integrity_log_query_keeps_extract_terms_without_operator_catalog_noise() -> None:
    normalized = normalize_query("File Integrity Operator에서 integritylog를 확인하고 압축 로그를 해제하는 명령어는 뭐야?")

    assert "integritylog" in normalized
    assert "base64" in normalized
    assert "gunzip" in normalized
    assert "ClusterServiceVersion" not in normalized
    assert "CatalogSource" not in normalized
    assert "InstallPlan" not in normalized
    assert "Subscription" not in normalized
    assert "oc logs" not in normalized


def test_postinstall_cluster_status_query_avoids_install_and_olm_noise() -> None:
    normalized = normalize_query("OpenShift 설치 후 클러스터 Operator와 노드 상태를 확인하는 기본 절차는 뭐야?")

    assert "oc get nodes" in normalized
    assert "clusteroperators" in normalized
    assert "postinstallation_configuration" in normalized
    assert "ClusterVersion" in normalized
    assert "Available" in normalized
    assert "NotReady" in normalized
    assert "Assisted Installer" not in normalized
    assert "Agent-based" not in normalized
    assert "openshift-install" not in normalized
    assert "ClusterServiceVersion" not in normalized
    assert "CatalogSource" not in normalized
    assert "InstallPlan" not in normalized


def test_postinstall_cluster_status_query_boosts_postinstallation_book() -> None:
    normalized = normalize_query("OpenShift 설치 후 클러스터 Operator와 노드 상태를 확인하는 기본 절차는 뭐야?")
    boosts, penalties = query_book_adjustments(normalized, context=SessionContext())

    assert boosts["postinstallation_configuration"] >= 2.65
    assert boosts["postinstallation_configuration"] > boosts.get("installation_overview", 1.0)
    assert penalties["nodes"] <= 0.72
    assert penalties["operators"] <= 0.72


def test_mcp_max_unavailable_query_targets_field_explanation_not_status_table() -> None:
    normalized = normalize_query("MachineConfigPool의 maxUnavailable 값은 어디서 설명하고 어떤 주의사항이 있어?")
    boosts, penalties = query_book_adjustments(normalized, context=SessionContext())

    assert "maxUnavailable" in normalized
    assert "MCO" in normalized
    assert "기본값 1" in normalized
    assert "3 으로 변경하지 마십시오" in normalized
    assert "updating_clusters" in normalized
    assert "oc get mcp" not in normalized
    assert "UPDATED" not in normalized
    assert "UPDATING" not in normalized
    assert "DEGRADED" not in normalized
    assert boosts["updating_clusters"] >= 2.35
    assert boosts["architecture"] >= 1.85
    assert penalties["nodes"] <= 0.42


def test_registry_pvc_query_targets_image_registry_field_not_generic_pvc() -> None:
    normalized = normalize_query(
        "이미지 레지스트리 스토리지를 PVC로 설정하려면 configs.imageregistry/cluster에서 어떤 필드를 바꿔야 해?"
    )

    assert "configs.imageregistry/cluster" in normalized
    assert "spec.storage.pvc" in normalized
    assert "Image" in normalized
    assert "openshift-image-registry" in normalized
    assert "allowVolumeExpansion" not in normalized


def test_etcd_restore_query_targets_restore_script_not_node_partition() -> None:
    normalized = normalize_query("OpenShift 4.20에서 etcd 스냅샷으로 클러스터를 복원할 때 restore 스크립트와 절차는 어디에 있어?")

    assert "cluster-restore.sh" in normalized
    assert "/usr/local/bin/cluster-restore.sh" in normalized
    assert "이전 클러스터 상태" in normalized
    assert "복원 절차" in normalized
    assert "lsblk" not in normalized
    assert "/var" not in normalized


def test_route_expose_query_targets_oc_expose_not_header_route() -> None:
    normalized = normalize_query("OpenShift에서 서비스를 외부로 노출하기 위해 Route를 생성하는 절차와 oc expose 명령어는 뭐야?")

    assert "oc expose" in normalized
    assert "service" in normalized
    assert "서비스" in normalized
    assert "노출" in normalized
    assert "HTTP 요청" not in normalized
    assert "app-example-route.yaml" not in normalized


def test_route_ingress_compare_query_avoids_expose_command_noise() -> None:
    normalized = normalize_query("OpenShift Route와 Kubernetes Ingress의 관계와 차이를 설명하는 공식 문서는 어디야?")

    assert "Route" in normalized
    assert "Ingress" in normalized
    assert "networking_overview" in normalized
    assert "oc expose" not in normalized
    assert "app-example-route.yaml" not in normalized


def test_oidc_auth_query_targets_auth_config_not_release_notes() -> None:
    normalized = normalize_query("외부 OIDC 인증 공급자를 설정할 때 authentication.config/cluster 구성 절차는 어디에 있어?")

    assert "authentication.config/cluster" in normalized
    assert "oc edit" in normalized
    assert "OIDC" in normalized
    assert "공급자" in normalized
    assert "release notes" not in normalized.lower()
    assert "OCPBUGS" not in normalized


def test_pod_pending_query_targets_scheduler_events_not_etcd_or_build_pods() -> None:
    normalized = normalize_query("Pod가 Pending 상태일 때 스케줄링 실패 원인과 이벤트를 확인하는 절차는 어떻게 돼?")

    assert "FailedScheduling" in normalized
    assert "oc describe pod" in normalized
    assert "get events" in normalized
    assert "openshift-etcd" not in normalized
    assert "source-to-image" not in normalized.lower()


def test_image_pruning_query_targets_pruner_not_tag_add_remove() -> None:
    normalized = normalize_query("OpenShift 이미지 레지스트리에서 오래된 이미지와 태그를 정리하는 pruning 절차는 어디에 있어?")

    assert "Pruner" in normalized
    assert "adm prune images" in normalized
    assert "pruning" in normalized
    assert "images" in normalized
    assert "oc tag -d" not in normalized


def test_mco_concept_query_targets_machine_configuration_not_node_status() -> None:
    normalized = normalize_query("Machine Config Operator가 노드 설정과 머신 구성을 관리하는 방식은 어디에 설명돼 있어?")
    boosts, penalties = query_book_adjustments(normalized, context=SessionContext())

    assert "Machine Config Operator" in normalized
    assert "machine_configuration" in normalized
    assert "machineconfigpool" in normalized.lower()
    assert "ClusterServiceVersion" not in normalized
    assert "oc get nodes" not in normalized
    assert boosts["machine_configuration"] >= 2.65
    assert penalties["nodes"] <= 0.42


def test_observability_monitoring_query_treats_each_purpose_as_compare() -> None:
    normalized = normalize_query("OpenShift observability와 monitoring 기능은 각각 어떤 목적으로 쓰이는지 설명해줘")
    boosts, penalties = query_book_adjustments(normalized, context=SessionContext())

    assert "Observability 정보" in normalized
    assert "monitoring" in normalized
    assert boosts["observability_overview"] >= 1.96
    assert boosts["monitoring"] >= 1.82
    assert penalties["support"] <= 0.38


def test_upgrade_precheck_query_keeps_command_signal() -> None:
    normalized = normalize_query("클러스터 업데이트 전에 oc adm upgrade recommend로 사전 점검하는 절차는 어디에 설명돼 있어?")

    assert "oc adm upgrade recommend" in normalized
    assert "릴리스 노트" in normalized
    assert "준비" in normalized


def test_web_console_doc_query_keeps_console_terms_without_cli_noise() -> None:
    normalized = normalize_query("OpenShift 웹 콘솔에서 클러스터 상태와 워크로드를 확인하는 기능은 어떤 문서에서 설명해?")

    assert "web console" in normalized.lower()
    assert "workloads" in normalized
    assert "Administrator perspective" in normalized
    assert "Developer" in normalized
    assert "oc CLI" not in normalized
    assert "명령어" not in normalized


def test_architecture_node_role_query_avoids_node_ops_noise() -> None:
    normalized = normalize_query("OpenShift 아키텍처에서 컨트롤 플레인과 컴퓨팅 노드는 각각 어떤 역할을 해?")

    assert "control plane" in normalized
    assert "compute node" in normalized
    assert "cluster architecture" in normalized
    assert "oc get nodes" not in normalized
    assert "oc debug" not in normalized
    assert "NotReady" not in normalized


def test_operator_csv_subscription_query_still_keeps_olm_terms() -> None:
    normalized = normalize_query("Operator가 Degraded일 때 CSV와 Subscription 상태를 어떻게 확인해?")

    assert "ClusterServiceVersion" in normalized
    assert "Subscription" in normalized
    assert "InstallPlan" in normalized
    assert "CatalogSource" in normalized


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
