import json

from play_book_studio.retrieval.query_signal_pipeline import build_query_signal_plan


class FakeSignalLlm:
    def __init__(self, payload: dict | None = None, *, error: Exception | None = None) -> None:
        self.payload = payload or {}
        self.error = error
        self.calls: list[dict] = []

    def generate(self, messages, *, max_tokens=None):
        self.calls.append({"messages": messages, "max_tokens": max_tokens})
        if self.error is not None:
            raise self.error
        return json.dumps(self.payload, ensure_ascii=False)


def _filter_keys(plan) -> set[str]:
    return {item["key"] for item in plan.metadata_filter["must"]}


def test_v015_query_signal_plan_handles_pvc_pending_one_shot() -> None:
    plan = build_query_signal_plan("PVC가 Pending인데 뭐 확인해야 해?")

    assert plan.classification["domain"] == "storage"
    assert "PVC" in plan.search_signals["objects"]
    assert "StorageClass" in plan.search_signals["objects"]
    assert "Pending" in plan.search_signals["error_states"]
    assert "check_status" in plan.search_signals["intent_labels"]
    assert "troubleshoot" in plan.search_signals["intent_labels"]
    assert "oc get pvc" in plan.search_signals["commands"]
    assert "oc describe pvc" in plan.search_signals["commands"]
    assert len(plan.embedding_queries) >= 2
    assert any("PersistentVolumeClaim" in query for query in plan.embedding_queries)
    assert plan.metadata_filter["_domain_filter_values"] == ("storage",)
    assert "search_signals.objects" not in _filter_keys(plan)


def test_query_signal_plan_keeps_route_header_rewrite_domain_specific() -> None:
    question = "Route에서 HTTP 요청/응답 헤더 설정을 정리하려면 어떻게 해?"
    plan = build_query_signal_plan(question)
    combined_queries = " ".join(plan.embedding_queries)

    assert plan.raw_query == question
    assert plan.classification["domain"] == "networking"
    assert "Route" in plan.search_signals["objects"]
    assert "Route HTTP header configuration" in plan.search_signals["primary_topics"]
    assert "oc -n app-example create -f app-example-route.yaml" in plan.search_signals["commands"]
    assert len(plan.embedding_queries) <= 2
    assert question in plan.embedding_queries[0]
    assert "HTTP request header" in combined_queries
    assert "HTTP response header" in combined_queries
    assert "Secret" not in combined_queries
    assert "ConfigMap" not in combined_queries
    assert "TLS" not in combined_queries
    assert "registry" not in combined_queries.lower()
    assert "ceph" not in combined_queries.lower()


def test_v015_query_signal_plan_extracts_etcd_backup_execution_target() -> None:
    plan = build_query_signal_plan("etcd 백업은 어느 노드에서 실행해?")

    assert plan.classification["domain"] == "etcd"
    assert "etcd" in plan.classification["book_slug_candidates"]
    assert "backup" in plan.search_signals["intent_labels"]
    assert "identify_execution_target" in plan.search_signals["intent_labels"]
    assert plan.search_signals["execution_target"] == ("control_plane_node",)
    assert "oc debug node/<control-plane-node>" in plan.search_signals["commands"]
    assert any("cluster-backup.sh" in query for query in plan.embedding_queries)
    assert "classification.book_slug" not in _filter_keys(plan)


def test_v015_query_signal_plan_expands_vsphere_dynamic_storage() -> None:
    plan = build_query_signal_plan("vSphere에서 PVC로 볼륨을 동적 프로비저닝하려면 어떻게 해?")

    assert plan.classification["domain"] == "storage"
    assert "storage" in plan.classification["book_slug_candidates"]
    assert "PVC" in plan.search_signals["objects"]
    assert "StorageClass" in plan.search_signals["objects"]
    assert "VMware vSphere" in plan.search_signals["primary_topics"]
    assert "dynamic provisioning" in plan.search_signals["primary_topics"]
    assert "oc_create" in plan.search_signals["command_families"]
    assert "oc create -f pvc.yaml" not in plan.search_signals["commands"]
    assert any("thin-csi" in query for query in plan.embedding_queries)


def test_v015_query_signal_plan_expands_vsphere_static_storage() -> None:
    plan = build_query_signal_plan("vSphere 볼륨을 정적으로 연결하려면 어떤 리소스를 만들어야 해?")

    assert plan.classification["domain"] == "storage"
    assert "PV" in plan.search_signals["objects"]
    assert "PVC" in plan.search_signals["objects"]
    assert "static provisioning" in plan.search_signals["primary_topics"]
    assert "oc_create" in plan.search_signals["command_families"]
    assert "oc create -f pv1.yaml" not in plan.search_signals["commands"]
    assert "oc create -f pvc1.yaml" not in plan.search_signals["commands"]
    assert any("static provisioning" in query for query in plan.embedding_queries)


def test_query_signal_plan_expands_general_static_storage_question() -> None:
    plan = build_query_signal_plan("정적 프로비저닝 기준으로 다음 확인 단계는 뭐야?")

    assert plan.classification["domain"] == "storage"
    assert "storage" in plan.classification["book_slug_candidates"]
    assert "PV" in plan.search_signals["objects"]
    assert "PVC" in plan.search_signals["objects"]
    assert "static provisioning" in plan.search_signals["primary_topics"]
    assert "oc_get" in plan.search_signals["command_families"]
    assert any("static provisioning" in query for query in plan.embedding_queries)


def test_v015_query_signal_plan_expands_install_compare_question() -> None:
    plan = build_query_signal_plan("UPI랑 agent-based 설치 차이 알려줘")

    assert plan.classification["domain"] == "install"
    assert plan.classification["platform"] == "any_platform"
    assert "install" in plan.search_signals["intent_labels"]
    assert "compare_options" in plan.search_signals["intent_labels"]
    assert "decision_guide" in plan.search_signals["answer_shapes"]
    assert any("Agent-based Installer" in query for query in plan.embedding_queries)
    assert plan.metadata_filter["_domain_filter_values"] == ("install",)


def test_v015_query_signal_plan_normalizes_image_pull_backoff_alias() -> None:
    plan = build_query_signal_plan("이미지풀백오프 뜨는데 pull secret 어디 봐?")

    assert plan.correction_notes
    assert "ImagePullBackOff" in plan.normalized_query
    assert plan.classification["domain"] == "registry"
    assert "Pod" in plan.search_signals["objects"]
    assert "Secret" in plan.search_signals["objects"]
    assert "ImagePullBackOff" in plan.search_signals["error_states"]
    assert "oc describe pod" in plan.search_signals["commands"]
    assert any("pull secret" in query for query in plan.embedding_queries)


def test_v015_query_signal_plan_normalizes_node_notready_alias() -> None:
    plan = build_query_signal_plan("노드가 노트레디면 처음에 뭐 봐야 함?")

    assert "Node" in plan.normalized_query
    assert "NotReady" in plan.normalized_query
    assert plan.classification["domain"] == "node_ops"
    assert "Node" in plan.search_signals["objects"]
    assert "NotReady" in plan.search_signals["error_states"]
    assert "oc get nodes" in plan.search_signals["commands"]
    assert "oc describe node" in plan.search_signals["commands"]
    assert any("kubelet" in query for query in plan.embedding_queries)
    assert {"key": "classification.domain", "match": {"value": "node_ops"}} not in plan.metadata_filter["must"]
    assert plan.metadata_filter["_domain_boosts"] == ("node_ops", "troubleshooting")
    assert plan.metadata_filter["_intent_signal_boosts"]["objects"] == ("Node",)
    assert "oc get nodes" in plan.metadata_filter["_intent_signal_boosts"]["commands"]


def test_query_signal_plan_expands_oc_login_command_alias() -> None:
    plan = build_query_signal_plan("ocp 로그인 어떻게 함")

    assert "command_lookup" in plan.search_signals["intent_labels"]
    assert "oc login -u <username>" in plan.search_signals["commands"]
    assert "oc whoami" in plan.search_signals["commands"]
    assert any("oc login -u <username>" in query for query in plan.embedding_queries)


def test_query_signal_plan_expands_pod_disruption_budget_alias() -> None:
    plan = build_query_signal_plan("모든 프로젝트에서 pod 중단 예산 확인 어떻게해?")

    assert "PodDisruptionBudget" in plan.search_signals["objects"]
    assert "PDB" in plan.search_signals["objects"]
    assert "oc get poddisruptionbudget --all-namespaces" in plan.search_signals["commands"]
    assert any("poddisruptionbudget --all-namespaces" in query for query in plan.embedding_queries)


def test_v015_query_signal_plan_uses_llm_one_shot_for_normalization_and_expansion() -> None:
    llm = FakeSignalLlm(
        {
            "normalized_query": "PVC가 Pending 상태인데 무엇을 확인해야 하나요?",
            "correction_notes": [
                {"type": "typo", "from": "Peding", "to": "Pending"},
            ],
            "classification": {
                "domain": "storage",
                "book_slug_candidates": ["storage"],
                "platform": "any_platform",
                "ocp_version": "4.20",
                "locale": "ko",
            },
            "search_signals": {
                "objects": ["PVC", "PV", "StorageClass"],
                "error_states": ["Pending"],
                "intent_labels": ["troubleshoot", "check_status", "command_lookup"],
                "answer_shapes": ["checklist", "command", "troubleshooting_flow"],
                "command_families": ["oc_get", "oc_describe"],
                "primary_topics": ["PVC", "PersistentVolumeClaim"],
                "secondary_topics": ["volume binding"],
                "components": ["CSI Driver"],
                "cluster_phase": ["incident", "day2"],
                "execution_target": ["cluster_admin_cli"],
                "commands": ["oc get pvc", "oc describe pvc"],
            },
            "confidence": {"domain": 0.95, "objects": 0.96, "commands": 0.91},
            "embedding_queries": [
                "PVC Pending 상태 확인 StorageClass PV Pod 이벤트",
                "oc get pvc oc describe pvc Pending volume binding troubleshooting",
                "PersistentVolumeClaim Pending storage provisioning StorageClass dynamic provisioning",
            ],
        }
    )

    plan = build_query_signal_plan("PVC가 Peding인데 뭐 확인해야 해?", llm_client=llm)

    assert llm.calls
    assert llm.calls[0]["max_tokens"] == 300
    assert plan.normalized_query == "PVC가 Pending 상태인데 무엇을 확인해야 하나요?"
    assert plan.correction_notes[0].type == "typo"
    assert plan.embedding_queries[0] == plan.normalized_query
    assert "PersistentVolumeClaim" in plan.embedding_queries[1]
    assert "oc get pvc" in plan.embedding_queries[1]
    assert plan.metadata_filter["_domain_filter_values"] == ("storage",)


def test_v015_query_signal_plan_sanitizes_llm_output_before_filtering() -> None:
    llm = FakeSignalLlm(
        {
            "normalized_query": "PVC 질문",
            "classification": {
                "domain": "made_up_domain",
                "book_slug_candidates": ["storage"],
                "platform": "unknown_platform",
            },
            "search_signals": {
                "intent_labels": ["troubleshoot", "unsafe_new_label"],
                "answer_shapes": ["command", "novel_shape"],
                "command_families": ["oc_get", "shell_everything"],
            },
            "confidence": {"domain": 1.0},
            "embedding_queries": ["PVC Pending"],
        }
    )

    plan = build_query_signal_plan("PVC가 Pending인데 뭐 확인해야 해?", llm_client=llm)

    assert plan.classification["domain"] == "storage"
    assert plan.classification["platform"] == "any_platform"
    assert "unsafe_new_label" not in plan.search_signals["intent_labels"]
    assert "novel_shape" not in plan.search_signals["answer_shapes"]
    assert "shell_everything" not in plan.search_signals["command_families"]
    assert plan.metadata_filter["_domain_filter_values"] == ("storage",)


def test_v015_query_signal_plan_maps_troubleshooting_domain_to_object_area() -> None:
    llm = FakeSignalLlm(
        {
            "normalized_query": "Node가 NotReady 상태일 때 무엇을 먼저 확인해야 하나요?",
            "classification": {
                "domain": "troubleshooting",
                "book_slug_candidates": ["troubleshooting_nodes"],
                "platform": "any_platform",
            },
            "search_signals": {
                "objects": ["Node"],
                "error_states": ["NotReady"],
                "intent_labels": ["troubleshoot", "check_status"],
                "answer_shapes": ["troubleshooting_flow", "command", "checklist"],
                "command_families": ["oc_get", "oc_describe"],
                "commands": ["oc get nodes", "oc describe node"],
            },
            "confidence": {"domain": 1.0, "objects": 1.0},
            "embedding_queries": ["OpenShift node NotReady troubleshooting steps"],
        }
    )

    plan = build_query_signal_plan("노드가 노트레디면 처음에 뭐 봐야 함?", llm_client=llm)

    assert plan.classification["domain"] == "node_ops"
    assert "troubleshoot" in plan.search_signals["intent_labels"]
    assert "check_status" in plan.search_signals["intent_labels"]
    assert {"key": "classification.domain", "match": {"value": "node_ops"}} not in plan.metadata_filter["must"]
    assert plan.metadata_filter["_domain_boosts"] == ("node_ops", "troubleshooting")
    assert plan.metadata_filter["_intent_signal_boosts"]["objects"] == ("Node",)
    assert "oc get nodes" in plan.metadata_filter["_intent_signal_boosts"]["commands"]


def test_metadata_filter_drops_uniform_must_conditions() -> None:
    plan = build_query_signal_plan("ocp 로그인 어떻게 함")
    keys = _filter_keys(plan)

    assert "source.enabled_for_chat" not in keys
    assert "source.review_status" not in keys
    assert "classification.locale" not in keys
    assert "classification.ocp_version" not in keys
    assert "chunk.navigation_only" not in keys


def test_metadata_filter_keeps_chat_scope_correctness_conditions() -> None:
    plan = build_query_signal_plan("ocp 로그인 어떻게 함")

    assert {"key": "source.citation_eligible", "match": {"value": True}} in plan.metadata_filter["must"]
    assert {"key": "source.corpus_scope", "match": {"value": "official_docs"}} in plan.metadata_filter["must"]
    assert {
        "key": "chunk.chunk_type",
        "match": {"any": ["command", "procedure", "concept", "reference", "troubleshooting"]},
    } in plan.metadata_filter["must"]


def test_v015_query_signal_plan_falls_back_when_llm_fails() -> None:
    plan = build_query_signal_plan(
        "노드가 노트레디면 처음에 뭐 봐야 함?",
        llm_client=FakeSignalLlm(error=RuntimeError("llm unavailable")),
    )

    assert "Node" in plan.normalized_query
    assert plan.classification["domain"] == "node_ops"
    assert "oc get nodes" in plan.search_signals["commands"]
