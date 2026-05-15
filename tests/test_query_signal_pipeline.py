from play_book_studio.retrieval.query_signal_pipeline import build_query_signal_plan


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
    assert {"key": "classification.domain", "match": {"value": "storage"}} in plan.metadata_filter["must"]
    assert "search_signals.objects" not in _filter_keys(plan)


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


def test_v015_query_signal_plan_expands_install_compare_question() -> None:
    plan = build_query_signal_plan("UPI랑 agent-based 설치 차이 알려줘")

    assert plan.classification["domain"] == "install"
    assert plan.classification["platform"] == "any_platform"
    assert "install" in plan.search_signals["intent_labels"]
    assert "compare_options" in plan.search_signals["intent_labels"]
    assert "decision_guide" in plan.search_signals["answer_shapes"]
    assert any("Agent-based Installer" in query for query in plan.embedding_queries)
    assert {"key": "classification.domain", "match": {"value": "install"}} in plan.metadata_filter["must"]


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
