from __future__ import annotations

from play_book_studio.answering.context import assemble_context
from play_book_studio.answering.answerer import _is_low_confidence_retrieval
from play_book_studio.answering.answer_text_commands import build_grounded_command_guide_answer
from play_book_studio.answering.answer_text_commands import build_grounded_status_answer
from play_book_studio.answering.answer_text_commands import strip_ungrounded_code_blocks
from play_book_studio.answering.answer_text_formatting import shape_beginner_grounded_answer
from play_book_studio.answering.models import AnswerResult, Citation
from play_book_studio.http.presenters import _citation_display_payload
from play_book_studio.http.session_flow import dedupe_suggestions, suggest_follow_up_questions
from play_book_studio.http.sessions import ChatSession
from play_book_studio.evals.studio_live_smoke import SmokeCase, _validate_case
from play_book_studio.retrieval.intent_profile import build_intent_profile
from play_book_studio.retrieval.intent_detectors import has_command_request
from play_book_studio.retrieval.models import RetrievalHit, SessionContext
from play_book_studio.retrieval.query_terms import normalize_query
from play_book_studio.retrieval.scoring import fuse_ranked_hits


def _hit(
    chunk_id: str,
    *,
    text: str,
    cli_commands: tuple[str, ...] = (),
    chunk_type: str = "reference",
    book_slug: str = "test-book",
    section: str = "Test Section",
    raw_score: float = 1.0,
) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        book_slug=book_slug,
        chapter="Test",
        section=section,
        anchor=chunk_id,
        source_url="",
        viewer_path=f"/docs/{chunk_id}",
        text=text,
        source="bm25",
        raw_score=raw_score,
        fused_score=raw_score,
        chunk_type=chunk_type,
        cli_commands=cli_commands,
    )


def _citation(
    *,
    excerpt: str = "Namespace and project commands.",
    cli_commands: tuple[str, ...] = ("oc get namespaces", "oc project -q"),
) -> Citation:
    return Citation(
        index=1,
        chunk_id="namespace-commands",
        book_slug="applications",
        section="Namespaces and projects",
        anchor="namespaces",
        source_url="",
        viewer_path="/docs/namespaces",
        excerpt=excerpt,
        cli_commands=cli_commands,
    )


def test_korean_command_lookup_is_detected_without_fixed_answer() -> None:
    assert has_command_request("네임스페이스 확인하는 명령어가 뭐야?")


def test_command_lookup_boosts_command_bearing_chunks() -> None:
    concept_hit = _hit(
        "concept",
        text="A namespace provides a scope for resources.",
    )
    command_hit = _hit(
        "command",
        text="Use oc get namespaces to list namespaces.",
        cli_commands=("oc get namespaces",),
        chunk_type="procedure",
    )

    hits = fuse_ranked_hits(
        "네임스페이스 확인하는 명령어가 뭐야?",
        {"bm25": [concept_hit, command_hit]},
        context=SessionContext(),
        top_k=2,
    )

    assert hits[0].chunk_id == "command"
    assert "command_intent_cli_commands_boost" in hits[0].component_scores


def test_intent_profile_prefers_matching_command_over_generic_cli_command() -> None:
    current_context_hit = _hit(
        "current-context",
        text="CLI profile commands show the selected project namespace. $ oc project",
        cli_commands=("oc project",),
        chunk_type="command",
        book_slug="cli_tools",
        raw_score=0.32,
    )
    namespace_list_hit = _hit(
        "namespace-list",
        text="List namespaces and projects with oc get namespaces or oc get projects.",
        cli_commands=("oc get namespaces", "oc get projects"),
        chunk_type="command",
        book_slug="cli_tools",
        raw_score=0.26,
    )

    hits = fuse_ranked_hits(
        "네임스페이스 목록 확인하려면 무슨 명령어를 쳐야 해?",
        {"bm25": [current_context_hit, namespace_list_hit]},
        context=SessionContext(),
        top_k=2,
    )

    assert hits[0].chunk_id == "namespace-list"
    assert hits[0].component_scores["intent_profile_primary_command_boost"] == 1.42
    assert "intent_profile_command_mismatch_penalty" in hits[1].component_scores


def test_command_context_selects_cli_profile_commands_instead_of_clarifying() -> None:
    query = "\ub124\uc784\uc2a4\ud398\uc774\uc2a4 \ud655\uc778\ud558\ub294 \uba85\ub839\uc5b4\uac00 \ubb50\uc57c?"
    concept_hit = _hit(
        "concept",
        text="A namespace scopes resources, but this paragraph has no command.",
        book_slug="security_and_compliance",
        raw_score=0.20,
    )
    cli_hit = _hit(
        "cli-profile",
        text=(
            "CLI profiles show the current context namespace. "
            "[CODE language=\"shell-session\"] $ oc config view [/CODE] "
            "[CODE language=\"shell-session\"] $ oc project [/CODE]"
        ),
        cli_commands=("oc config view", "oc project"),
        chunk_type="command",
        book_slug="cli_tools",
        section="2.4.2. CLI profile manual configuration",
        raw_score=0.18,
    )

    bundle = assemble_context([concept_hit, cli_hit], query=query, max_chunks=4)

    assert bundle.citations
    assert bundle.citations[0].chunk_id == "cli-profile"
    assert "oc config view" in bundle.citations[0].cli_commands


def test_current_project_command_context_prefers_view_over_set_context() -> None:
    query = (
        "\ud604\uc7ac \ud130\ubbf8\ub110\uc774 \uc5b4\ub290 \ud504\ub85c\uc81d\ud2b8\ub098 "
        "namespace\ub97c \ubcf4\uace0 \uc788\ub294\uc9c0 \ud655\uc778\ud558\ub294 \uba85\ub839\uc740?"
    )
    set_context_hit = _hit(
        "set-context",
        text=(
            "CLI profile manual configuration. "
            "[CODE language=\"shell-session\"] $ oc config set-context `oc config current-context` "
            "--namespace=<project_name> [/CODE]"
        ),
        cli_commands=("oc config set-context `oc config current-context` --namespace=<project_name>",),
        chunk_type="command",
        book_slug="cli_tools",
        section="2.4.2. CLI profile manual configuration",
        raw_score=0.30,
    )
    view_project_hit = _hit(
        "view-project",
        text=(
            "현재 프로젝트 보기. 아래 명령을 사용하여 현재 프로젝트를 봅니다. "
            "[CODE language=\"shell\"] oc project [/CODE]"
        ),
        cli_commands=("oc project",),
        chunk_type="command",
        book_slug="cli_tools",
        section="2.1.5.5. 현재 프로젝트 보기",
        raw_score=0.20,
    )

    bundle = assemble_context([set_context_hit, view_project_hit], query=query, max_chunks=4)

    assert bundle.citations
    assert bundle.citations[0].chunk_id == "view-project"


def test_namespace_command_query_expands_toward_cli_profile_docs() -> None:
    profile = build_intent_profile(
        "\ub124\uc784\uc2a4\ud398\uc774\uc2a4 \ud655\uc778\ud558\ub294 \uba85\ub839\uc5b4\uac00 \ubb50\uc57c?"
    )
    normalized = normalize_query(
        "\ub124\uc784\uc2a4\ud398\uc774\uc2a4 \ud655\uc778\ud558\ub294 \uba85\ub839\uc5b4\uac00 \ubb50\uc57c?"
    )

    assert profile.intent == "command_lookup"
    assert profile.target_object == "namespace"
    assert profile.primary_commands == ("oc project", "oc config view")
    assert "현재 프로젝트 보기" in normalized
    assert "config view" in normalized


def test_namespace_list_command_query_expands_toward_namespace_list_docs() -> None:
    profile = build_intent_profile("네임스페이스 목록 확인하려면 무슨 명령어를 쳐야 해?")
    normalized = normalize_query("네임스페이스 목록 확인하려면 무슨 명령어를 쳐야 해?")

    assert profile.intent == "command_lookup"
    assert profile.task == "list"
    assert profile.primary_commands == ("oc get namespaces", "oc get projects")
    assert "namespaces" in normalized
    assert "projects" in normalized


def test_install_guidance_context_selects_bootstrap_wait_command() -> None:
    query = "bootstrap \uae30\ub2e4\ub9ac\ub294 \ub2e8\uacc4\uc5d0\uc11c \ubb58 \ud655\uc778\ud574\uc57c \ud574?"
    overview_hit = _hit(
        "overview",
        text="The bootstrap process prepares initial cluster services.",
        book_slug="installation_overview",
        raw_score=0.20,
    )
    wait_hit = _hit(
        "bootstrap-wait",
        text=(
            "Waiting for the bootstrap process to complete. "
            "[CODE language=\"shell-session\"] "
            "$ ./openshift-install --dir <installation_directory> wait-for bootstrap-complete --log-level=info "
            "[/CODE]"
        ),
        chunk_type="procedure",
        book_slug="installing_on_any_platform",
        section="1.14. Waiting for the bootstrap process to complete",
        raw_score=0.18,
    )

    bundle = assemble_context([overview_hit, wait_hit], query=query, max_chunks=4)

    assert bundle.citations
    assert bundle.citations[0].chunk_id == "bootstrap-wait"
    assert any("openshift-install" in command for command in bundle.citations[0].cli_commands)


def test_bootstrap_guidance_query_expands_toward_wait_doc() -> None:
    normalized = normalize_query(
        "bootstrap \uae30\ub2e4\ub9ac\ub294 \ub2e8\uacc4\uc5d0\uc11c \ubb58 \ud655\uc778\ud574\uc57c \ud574?"
    )

    assert "Waiting" in normalized
    assert "process" in normalized
    assert "complete" in normalized
    assert "wait-for bootstrap-complete" in normalized


def test_clusteroperator_korean_query_expands_to_clusteroperator_command() -> None:
    profile = build_intent_profile("클러스터 오퍼레이터가 Degraded인지 한 번에 보는 명령어 알려줘")
    normalized = normalize_query("클러스터 오퍼레이터가 Degraded인지 한 번에 보는 명령어 알려줘")

    assert profile.target_object == "clusteroperator"
    assert profile.primary_commands[0] == "oc get clusteroperators"
    assert "ClusterOperator" in profile.evidence_terms
    assert "clusteroperators" in normalized


def test_command_learning_query_expands_node_debug_and_mcp_terms() -> None:
    node_profile = build_intent_profile("노드 호스트에 들어가서 확인하려면 oc debug 다음에 뭘 쳐야 해?")
    mcp_profile = build_intent_profile("MachineConfigPool 적용이 늦을 때 상태 확인하는 명령어 뭐부터 봐?")
    node_debug = normalize_query("노드 호스트에 들어가서 확인하려면 oc debug 다음에 뭘 쳐야 해?")
    mcp = normalize_query("MachineConfigPool 적용이 늦을 때 상태 확인하는 명령어 뭐부터 봐?")

    assert node_profile.task == "host-debug"
    assert node_profile.primary_commands == ("oc debug node/<node-name>", "chroot /host")
    assert mcp_profile.target_object == "machineconfigpool"
    assert mcp_profile.primary_commands[0] == "oc get mcp"
    assert "chroot /host" in node_debug
    assert "machine config pool" in mcp_profile.evidence_terms
    assert "machine-config" in mcp


def test_command_learning_profiles_cover_access_pvc_logs_routes_and_etcd() -> None:
    previous_logs = build_intent_profile("pod 이전 로그 확인하려면 무슨 명령어를 써?")
    pvc = build_intent_profile("PVC가 Pending이면 뭐부터 확인하는 명령어가 좋아?")
    rbac = build_intent_profile("alice가 pods delete 권한 있는지 can-i로 확인하는 명령어 뭐야?")
    route = build_intent_profile("route랑 service 연결 상태 확인하는 명령어 알려줘")
    etcd = build_intent_profile("etcd 백업하려면 oc debug 이후에 어떤 명령 흐름이야?")

    assert previous_logs.primary_commands == ("oc logs <pod-name> -n <namespace> --previous",)
    assert pvc.target_object == "persistentvolumeclaim"
    assert "oc describe pvc <pvc-name> -n <namespace>" in pvc.primary_commands
    assert rbac.primary_commands[0] == "oc auth can-i delete pods -n <namespace>"
    assert "oc get service -n <namespace>" in route.primary_commands
    assert "chroot /host" in etcd.primary_commands
    assert "cluster-backup.sh" in etcd.primary_commands


def test_beginner_ops_profiles_do_not_collapse_to_namespace_lookup() -> None:
    rbac = build_intent_profile("현재 사용자가 특정 namespace에서 pods를 delete 할 수 있는지 확인하는 명령은?")
    login = build_intent_profile("oc login이 실패할 때 토큰이나 서버 URL 문제를 먼저 어떻게 확인해?")
    quota = build_intent_profile("ResourceQuota 때문에 Pod 생성이 막힌 건지 확인하려면 어디를 봐?")
    limit = build_intent_profile("LimitRange 때문에 컨테이너 리소스 요청이 거절될 수 있는지 확인하려면?")
    image_pull = build_intent_profile("ImagePullBackOff가 뜰 때 pull secret과 registry 쪽을 어떤 순서로 확인해?")
    node = build_intent_profile("Node 확인하려면 어떤 명령어부터 쓰면 돼?")
    namespace = build_intent_profile("네임스페이스 확인하는 명령어가 뭐야?")
    network = build_intent_profile("NetworkPolicy 때문에 Pod 통신이 막힌 건지 확인하려면 뭘 봐야 해?")
    dns = build_intent_profile("클러스터 DNS 문제가 의심되면 어떤 리소스 상태부터 확인해야 해?")
    mco = build_intent_profile("Machine Config Operator 상태를 먼저 확인하는 명령을 알려줘")
    cvo = build_intent_profile("Cluster Version Operator가 업데이트를 못 하고 있으면 어디부터 확인해?")
    registry = build_intent_profile("허용된 registry만 쓰도록 제한하는 설정은 어디서 확인해?")
    must_gather = build_intent_profile("장애 분석용 must-gather는 언제 어떤 명령으로 수집해?")
    inspect = build_intent_profile("특정 namespace 리소스 상태를 지원팀에 전달하려면 oc adm inspect를 써야 해?")
    top_pods = build_intent_profile("namespace 안에서 CPU를 많이 쓰는 Pod를 찾는 명령은 뭐야?")
    pod_usage = build_intent_profile("특정 Pod의 리소스가 얼마나 잡아먹고 있는지 확인하는 법")

    assert rbac.target_object == "rbac"
    assert rbac.primary_commands[0] == "oc auth can-i delete pods -n <namespace>"
    assert login.target_object == "oc-login"
    assert login.primary_commands[0] == "oc login --token=<token> --server=<api-url>"
    assert quota.target_object == "resourcequota"
    assert "ResourceQuota" in quota.evidence_terms
    assert limit.target_object == "limitrange"
    assert "LimitRange" in limit.evidence_terms
    assert image_pull.task == "image-pull"
    assert "ImagePullBackOff" in image_pull.evidence_terms
    assert node.target_object == "node"
    assert node.primary_commands[0] == "oc get nodes"
    assert namespace.target_object == "namespace"
    assert namespace.primary_commands[0] == "oc project"
    assert network.target_object == "networkpolicy"
    assert "NetworkPolicy" in network.evidence_terms
    assert dns.target_object == "dns"
    assert "openshift-dns" in dns.evidence_terms
    assert mco.target_object == "machineconfigpool"
    assert "Machine Config Operator" in mco.evidence_terms
    assert cvo.target_object == "clusterversion"
    assert "Cluster Version Operator" in cvo.evidence_terms
    assert registry.target_object == "image-config"
    assert "allowedRegistries" in registry.evidence_terms
    assert must_gather.target_object == "must-gather"
    assert must_gather.primary_commands[0] == "oc adm must-gather"
    assert inspect.target_object == "inspect"
    assert inspect.primary_commands[0].startswith("oc adm inspect")
    assert top_pods.target_object == "pod-metrics"
    assert top_pods.primary_commands[0].startswith("oc adm top pod")
    assert pod_usage.target_object == "pod-metrics"
    assert "CPU" in pod_usage.evidence_terms


def test_context_assembly_recovers_intent_evidence_outside_command_book_lock() -> None:
    quota_hit = _hit(
        "resourcequota-kmsc",
        text=(
            "ResourceQuota 생성 후 확인. kind: ResourceQuota. "
            "hard pods requests.cpu requests.memory. oc get resourcequotas -n chak-test"
        ),
        book_slug="kmsc-operations",
        section="OCP 프로젝트 관리 테스트",
        raw_score=0.9,
    )
    unrelated_cli_hit = _hit(
        "pod-top",
        text="Pod CPU memory metrics. oc adm top pod --namespace=NAMESPACE",
        cli_commands=("oc adm top pod --namespace=NAMESPACE",),
        book_slug="cli_tools",
        section="oc adm top pod",
        raw_score=0.7,
    )

    bundle = assemble_context(
        [quota_hit, unrelated_cli_hit],
        query="ResourceQuota 때문에 Pod 생성이 막힌 건지 확인하려면 어디를 봐?",
        max_chunks=4,
    )

    assert bundle.citations
    assert bundle.citations[0].chunk_id == "resourcequota-kmsc"


def test_command_signal_matching_is_case_insensitive() -> None:
    citation = _citation(
        excerpt="ResourceQuota hard/used 값을 보고 quota 초과 여부를 판단합니다.",
        cli_commands=("oc get resourcequota -n <namespace>",),
    )

    answer = build_grounded_command_guide_answer(
        query="ResourceQuota 때문에 Pod 생성이 막힌 건지 확인하려면 어디를 봐?",
        citations=[citation],
    )

    assert answer is not None
    assert "ResourceQuota" in answer
    assert "oc get resourcequota" in answer


def test_resourcequota_answer_prefers_read_only_grounded_command() -> None:
    citation = _citation(
        excerpt="ResourceQuota hard/used 값을 보고 quota 초과 여부를 판단합니다.",
        cli_commands=(
            "oc patch resourcequotas test-compute -n chak-test --type=merge --patch "
            '\'{"spec":{"hard":{"pods":"2"}}}\' # oc get resourcequotas -n chak-test CLI 또는 Web Console 에서 확인',
        ),
    )

    answer = build_grounded_command_guide_answer(
        query="ResourceQuota 때문에 Pod 생성이 막힌 건지 확인하려면 어디를 봐?",
        citations=[citation],
    )

    assert answer is not None
    assert "oc get resourcequotas -n chak-test" in answer
    assert "oc patch resourcequotas" not in answer


def test_beginner_shape_preserves_specific_resourcequota_answer() -> None:
    citation = _citation(
        excerpt="ResourceQuota hard/used 값을 보고 quota 초과 여부를 판단합니다.",
        cli_commands=("oc get resourcequotas -n chak-test",),
    )
    answer = build_grounded_command_guide_answer(
        query="ResourceQuota 때문에 Pod 생성이 막힌 건지 확인하려면 어디를 봐?",
        citations=[citation],
    )

    shaped = shape_beginner_grounded_answer(
        answer or "",
        query="ResourceQuota 때문에 Pod 생성이 막힌 건지 확인하려면 어디를 봐?",
        citations=[citation],
    )

    assert "ResourceQuota 때문에 Pod 생성이 막혔는지는" in shaped
    assert "명령어 확인 요청" not in shaped


def test_embedded_cli_text_is_split_before_answering() -> None:
    network = _citation(
        excerpt="NetworkPolicy가 Pod 통신을 제한할 수 있습니다.",
        cli_commands=("oc edit template <project_template> -n openshift-config oc new-project <project> oc get networkpolicy oc",),
    )
    node = _citation(
        excerpt="노드 목록에서 Ready 상태를 확인합니다.",
        cli_commands=("oc get node show-labels' 명령어 실행 결과인 노드 목록이 표시되어 있습니다.",),
    )

    network_answer = build_grounded_command_guide_answer(
        query="NetworkPolicy 때문에 Pod 통신이 막힌 건지 확인하려면 뭘 봐야 해?",
        citations=[network],
    )
    node_answer = build_grounded_command_guide_answer(
        query="Node 확인하려면 어떤 명령어부터 쓰면 돼?",
        citations=[node],
    )

    assert network_answer is not None
    assert "oc get networkpolicy" in network_answer
    assert "oc edit template" not in network_answer
    assert node_answer is not None
    assert "명령어 실행 결과" not in node_answer


def test_beginner_command_lookup_sanitizes_embedded_cli_text() -> None:
    citation = _citation(
        excerpt="노드 목록에서 Ready 상태를 확인합니다.",
        cli_commands=("oc get node show-labels' 명령어 실행 결과인 노드 목록이 표시되어 있습니다.",),
    )

    answer = shape_beginner_grounded_answer(
        "확인하면 됩니다.",
        query="Node 확인하려면 어떤 명령어부터 쓰면 돼?",
        citations=[citation],
    )

    assert "oc get node show-labels" in answer
    assert "명령어 실행 결과" not in answer


def test_status_answer_handles_basic_node_command_lookup() -> None:
    citation = _citation(
        excerpt="Node 목록에서 Ready 상태를 확인하고 문제가 있으면 describe로 Conditions와 Events를 봅니다.",
        cli_commands=("oc get nodes", "oc describe node <node-name>"),
    )

    answer = build_grounded_status_answer(
        query="Node 확인하려면 어떤 명령어부터 쓰면 돼?",
        citations=[citation],
    )

    assert answer is not None
    assert "oc get nodes" in answer
    assert "oc describe node" in answer
    assert "Ready" in answer


def test_status_answer_distinguishes_namespace_current_context_from_list() -> None:
    current = _citation(
        excerpt="현재 프로젝트와 namespace context는 oc project 또는 oc config view로 확인합니다.",
        cli_commands=("oc project", "oc config view --minify"),
    )
    listing = _citation(
        excerpt="전체 namespace 목록은 oc get namespaces 또는 oc get projects로 조회합니다.",
        cli_commands=("oc get namespaces", "oc get projects"),
    )

    current_answer = build_grounded_status_answer(
        query="네임스페이스 확인하는 명령어가 뭐야?",
        citations=[current, listing],
    )
    list_answer = build_grounded_status_answer(
        query="네임스페이스 목록 확인하려면 무슨 명령어를 쳐야 해?",
        citations=[listing, current],
    )

    assert current_answer is not None
    assert "oc project" in current_answer
    assert "oc get namespaces" not in current_answer
    assert list_answer is not None
    assert "oc get namespaces" in list_answer


def test_status_answer_handles_image_pull_without_clarification_shape() -> None:
    citation = _citation(
        excerpt="ImagePullBackOff는 Pod 이벤트와 pull secret, registry 접근을 확인합니다.",
        cli_commands=(
            "oc describe pod <pod-name> -n <namespace>",
            "oc get secret -n <namespace>",
            "oc secrets link default <pull-secret> --for=pull -n <namespace>",
        ),
    )

    answer = build_grounded_status_answer(
        query="ImagePullBackOff가 뜰 때 pull secret과 registry 쪽을 어떤 순서로 확인해?",
        citations=[citation],
    )

    assert answer is not None
    assert "ImagePullBackOff" in answer
    assert "oc describe pod" in answer
    assert "oc secrets link" in answer


def test_status_answer_handles_support_collection_commands_without_ungrounded_code_blocks() -> None:
    must_gather = _citation(
        excerpt="must-gather collects diagnostic data for support and troubleshooting.",
        cli_commands=(),
    )
    inspect = _citation(
        excerpt="oc adm inspect can gather resource status for a namespace before support handoff.",
        cli_commands=(),
    )

    must_answer = build_grounded_status_answer(
        query="장애 분석용 must-gather는 언제 어떤 명령으로 수집해?",
        citations=[must_gather],
    )
    inspect_answer = build_grounded_status_answer(
        query="특정 namespace 리소스 상태를 지원팀에 전달하려면 oc adm inspect를 써야 해?",
        citations=[inspect],
    )

    assert must_answer is not None
    assert "must-gather" in must_answer
    assert "```" not in must_answer
    assert inspect_answer is not None
    assert "oc adm inspect" in inspect_answer
    assert "```" not in inspect_answer


def test_status_answer_handles_top_pods_plural_query_from_singular_cli_docs() -> None:
    citation = _citation(
        excerpt="Show metrics for all pods in the given namespace with oc adm top pod --namespace=NAMESPACE.",
        cli_commands=("oc adm top pod --namespace=NAMESPACE",),
    )

    answer = build_grounded_status_answer(
        query="namespace 안에서 CPU를 많이 쓰는 Pod를 찾는 명령은 뭐야?",
        citations=[citation],
    )

    assert answer is not None
    assert "oc adm top pods" in answer
    assert "oc adm top pod --namespace=NAMESPACE" in answer


def test_command_sanitize_preserves_balanced_selector_quotes() -> None:
    citation = _citation(
        excerpt="Pod usage metrics can be filtered by selector.",
        cli_commands=("oc adm top pod --selector='<pod_name>'",),
    )

    answer = build_grounded_status_answer(
        query="특정 Pod의 리소스가 얼마나 잡아먹고 있는지 확인하는 법",
        citations=[citation],
    )

    assert answer is not None
    assert "oc adm top pod --selector='<pod_name>'" in answer


def test_clusteroperator_answer_uses_inline_fallback_when_citation_has_no_command() -> None:
    citation = _citation(
        excerpt="클러스터 Operator 상태에는 Available, Progressing, Degraded 조건이 있습니다.",
        cli_commands=(),
    )

    answer = build_grounded_status_answer(
        query="ClusterOperator가 Degraded일 때 전체 상태를 한 번에 보는 명령은?",
        citations=[citation],
    )

    assert answer is not None
    assert "oc get clusteroperators" in answer
    assert "```" not in answer


def test_low_confidence_guard_allows_operational_intent_overlap() -> None:
    citation = _citation(
        excerpt="ImagePullBackOff 상태에서는 pull secret과 registry 접근 오류를 확인합니다.",
        cli_commands=("oc describe pod <pod-name> -n <namespace>",),
    )

    assert not _is_low_confidence_retrieval(
        query="ImagePullBackOff가 뜰 때 pull secret과 registry 쪽을 어떤 순서로 확인해?",
        citations=[citation],
        selected_hits=[{"fused_score": 0.0, "pre_rerank_fused_score": 0.0, "vector_score": 0.0}],
    )
    finalizer = _citation(
        excerpt="A namespace stuck in Terminating can have remaining finalizers on resources.",
        cli_commands=("oc get namespace <namespace> -o yaml",),
    )

    assert not _is_low_confidence_retrieval(
        query="namespace가 Terminating에서 안 없어질 때 finalizer와 남은 리소스를 어떻게 확인해?",
        citations=[finalizer],
        selected_hits=[{"fused_score": 0.0, "pre_rerank_fused_score": 0.0, "vector_score": 0.0}],
    )
    pod_usage = _citation(
        excerpt="Show metrics for all pods in the given namespace with oc adm top pod --namespace=NAMESPACE.",
        cli_commands=("oc adm top pod --namespace=NAMESPACE",),
    )

    assert not _is_low_confidence_retrieval(
        query="특정 Pod의 리소스가 얼마나 잡아먹고 있는지 확인하는 법",
        citations=[pod_usage],
        selected_hits=[{"fused_score": 0.0, "pre_rerank_fused_score": 0.0, "vector_score": 0.0}],
    )


def test_low_confidence_guard_allows_bootstrap_wait_grounding() -> None:
    citation = _citation(
        excerpt="Use openshift-install wait-for bootstrap-complete to monitor bootstrap.",
        cli_commands=("openshift-install --dir <installation_directory> wait-for bootstrap-complete --log-level=info",),
    )

    assert not _is_low_confidence_retrieval(
        query="bootstrap \uae30\ub2e4\ub9ac\ub294 \ub2e8\uacc4\uc5d0\uc11c \ubb58 \ud655\uc778\ud574\uc57c \ud574?",
        citations=[citation],
        selected_hits=[{"fused_score": 0.03, "pre_rerank_fused_score": 0.02, "vector_score": 0.02}],
    )


def test_strip_ungrounded_code_blocks_does_not_claim_no_commands_when_citation_has_command() -> None:
    citation = _citation(
        excerpt="Use openshift-install wait-for bootstrap-complete to monitor bootstrap.",
        cli_commands=("openshift-install --dir <installation_directory> wait-for bootstrap-complete --log-level=info",),
    )

    cleaned = strip_ungrounded_code_blocks(
        "답변\n\n```text\nINFO Waiting for API...\n```",
        citations=[citation],
    )

    assert "제공된 근거에는 실행 명령" not in cleaned


def test_namespace_command_answer_is_built_from_citation_commands() -> None:
    answer = build_grounded_command_guide_answer(
        query="네임스페이스 확인하는 명령어가 뭐야?",
        citations=[_citation()],
    )

    assert answer is not None
    assert "oc project -q" in answer
    assert "oc get namespaces" not in answer


def test_follow_up_questions_are_grounded_in_citation_commands() -> None:
    result = AnswerResult(
        query="네임스페이스 확인하는 명령어가 뭐야?",
        mode="chat",
        answer="답변: `oc get namespaces`를 사용하세요 [1].",
        rewritten_query="네임스페이스 확인하는 명령어가 뭐야?",
        response_kind="rag",
        citations=[_citation()],
        cited_indices=[1],
    )

    suggestions = suggest_follow_up_questions(session=ChatSession(session_id="s1"), result=result)

    assert suggestions
    assert any("oc get namespaces" in suggestion for suggestion in suggestions)
    assert all("문서" not in suggestion for suggestion in suggestions[:1])


def test_follow_up_questions_rotate_from_citation_seed_and_stay_grounded() -> None:
    first = AnswerResult(
        query="현재 프로젝트 확인 명령은?",
        mode="chat",
        answer="답변: `oc project` [1].",
        rewritten_query="현재 프로젝트 확인 명령은?",
        response_kind="rag",
        citations=[_citation(cli_commands=("oc project",), excerpt="현재 프로젝트 보기")],
        cited_indices=[1],
    )
    second = AnswerResult(
        query="bootstrap 기다리는 단계에서 뭘 확인해야 해?",
        mode="chat",
        answer="답변: `openshift-install wait-for bootstrap-complete` [1].",
        rewritten_query="bootstrap 기다리는 단계에서 뭘 확인해야 해?",
        response_kind="rag",
        citations=[
            _citation(
                excerpt="Waiting for the bootstrap process to complete.",
                cli_commands=("openshift-install --dir <installation_directory> wait-for bootstrap-complete --log-level=info",),
            )
        ],
        cited_indices=[1],
    )

    first_suggestions = suggest_follow_up_questions(session=ChatSession(session_id="s1"), result=first)
    second_suggestions = suggest_follow_up_questions(session=ChatSession(session_id="s2"), result=second)

    assert first_suggestions
    assert second_suggestions
    assert first_suggestions != second_suggestions
    assert any("oc project" in suggestion or "namespace" in suggestion for suggestion in first_suggestions)
    assert any("bootstrap" in suggestion or "openshift-install" in suggestion for suggestion in second_suggestions)


def test_follow_up_suggestions_filter_mojibake_like_text_without_literal_glyphs() -> None:
    broken = "\u8b1b\u4e11\u89c0\u4e11 기준으로 설명해줘"
    suggestions = dedupe_suggestions(
        [
            broken,
            "네임스페이스 상태 확인 방법을 알려줘",
            "oc get namespaces 결과에서 무엇을 확인해야 해?",
        ],
        query="namespace 확인 명령어가 뭐야?",
    )

    assert broken not in suggestions
    assert suggestions == [
        "네임스페이스 상태 확인 방법을 알려줘",
        "oc get namespaces 결과에서 무엇을 확인해야 해?",
    ]


def test_citation_display_payload_strips_code_markup() -> None:
    payload = _citation_display_payload(
        _citation(
            excerpt='[CODE language="shell-session" caption="Monitor"] $ oc get namespaces [/CODE]',
            cli_commands=("oc get namespaces",),
        )
    )

    assert "[CODE" not in payload["excerpt"]
    assert "[/CODE" not in payload["excerpt"]
    assert "oc get namespaces" in payload["excerpt"]
    assert payload["command_preview"] == ["oc get namespaces"]


def test_live_smoke_flags_command_answers_without_grounded_command() -> None:
    detail = _validate_case(
        SmokeCase(case_id="command-missing", query="네임스페이스 확인하는 명령어가 뭐야?"),
        200,
        [
            {"type": "answer_delta"},
            {
                "type": "result",
                "payload": {
                    "answer": "답변: 관련 문서를 먼저 확인하세요 [1].",
                    "response_kind": "rag",
                    "warnings": [],
                    "cited_indices": [1],
                    "suggested_queries": [],
                    "citations": [
                        {
                            "index": 1,
                            "book_slug": "applications",
                            "section": "Namespaces",
                            "viewer_path": "/docs/namespaces",
                            "excerpt": "Namespace overview.",
                            "cli_commands": [],
                        }
                    ],
                },
            },
        ],
        "",
    )

    assert "command_query_missing_grounded_command" in detail["failures"]


def test_live_smoke_flags_raw_code_markup_in_citation_preview() -> None:
    detail = _validate_case(
        SmokeCase(case_id="raw-code", query="네임스페이스 확인하는 명령어가 뭐야?"),
        200,
        [
            {"type": "answer_delta"},
            {
                "type": "result",
                "payload": {
                    "answer": "답변: 아래 명령을 사용하세요 [1].\n\n```bash\noc get namespaces\n```",
                    "response_kind": "rag",
                    "warnings": [],
                    "cited_indices": [1],
                    "suggested_queries": ["`oc get namespaces` 결과에서 무엇을 확인해야 해?"],
                    "citations": [
                        {
                            "index": 1,
                            "book_slug": "applications",
                            "section": "Namespaces",
                            "viewer_path": "/docs/namespaces",
                            "excerpt": "[CODE] oc get namespaces [/CODE]",
                            "cli_commands": ["oc get namespaces"],
                        }
                    ],
                },
            },
        ],
        "",
    )

    assert "citation_raw_code_markup" in detail["failures"]


def test_live_smoke_flags_missing_command_learning_terms() -> None:
    detail = _validate_case(
        SmokeCase(
            case_id="v006-missing-term",
            query="노드 CPU랑 메모리 사용량을 확인하는 oc 명령어 뭐야?",
            must_include_terms=("oc adm top nodes",),
            expected_citation_terms=("oc adm top nodes",),
        ),
        200,
        [
            {"type": "answer_delta"},
            {
                "type": "result",
                "payload": {
                    "answer": "답변: 노드 상태는 관련 문서의 절차를 확인하세요 [1].",
                    "response_kind": "rag",
                    "warnings": [],
                    "cited_indices": [1],
                    "suggested_queries": [],
                    "citations": [
                        {
                            "index": 1,
                            "book_slug": "nodes",
                            "section": "노드",
                            "viewer_path": "/docs/nodes",
                            "excerpt": "Node overview.",
                            "cli_commands": [],
                        }
                    ],
                },
            },
        ],
        "",
    )

    assert "missing_required_term:oc adm top nodes" in detail["failures"]
    assert "missing_citation_term:oc adm top nodes" in detail["failures"]
