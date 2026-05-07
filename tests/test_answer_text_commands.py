from play_book_studio.answering.answer_text_commands import (
    build_grounded_command_guide_answer,
    shape_crash_loop_troubleshooting,
    strip_ungrounded_code_blocks,
)
from play_book_studio.answering.citations import finalize_citations
from play_book_studio.answering.models import Citation


def test_grounded_command_guide_includes_verification_hints() -> None:
    citation = Citation(
        index=1,
        chunk_id="installation_overview--runtimes",
        book_slug="installation_overview",
        section="4.4.3. Runtimes",
        anchor="runtimes",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/installation_overview/index.html#runtimes",
        excerpt="Runtimes 절차에서는 노드와 머신 상태를 확인합니다.",
        cli_commands=("oc get nodes", "oc get machines -A"),
        verification_hints=("노드가 Ready 상태인지 확인", "Machine이 Running 상태인지 확인"),
    )

    answer = build_grounded_command_guide_answer(
        query="Runtimes 절차 명령 알려줘",
        citations=[citation],
    )

    assert answer is not None
    assert "oc get nodes" in answer
    finalized, _, _ = finalize_citations(answer, [citation])
    assert (
        "실행 후에는 노드가 Ready 상태인지 확인; Machine이 Running 상태인지 확인 기준으로 결과를 확인하세요. [1]"
        in finalized
    )


def test_finalize_citations_places_period_before_citation_marker() -> None:
    citation = Citation(
        index=1,
        chunk_id="c1",
        book_slug="installation_overview",
        section="Runtimes",
        anchor="runtimes",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/installation_overview/index.html#runtimes",
        excerpt="",
    )

    finalized, _, _ = finalize_citations("답변: 아래 명령으로 진행하면 됩니다 [1].", [citation])

    assert finalized == "답변: 아래 명령으로 진행하면 됩니다. [1]"


def test_finalize_citations_normalizes_korean_particle_spacing() -> None:
    citation = Citation(
        index=1,
        chunk_id="c1",
        book_slug="nodes",
        section="HPA",
        anchor="hpa",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/nodes/index.html#hpa",
        excerpt="",
    )

    finalized, _, _ = finalize_citations(
        "답변: HPA 는 15 초마다 Pod 의 지표를 확인합니다 [1].",
        [citation],
    )

    assert finalized == "답변: HPA는 15초마다 Pod의 지표를 확인합니다. [1]"


def test_finalize_citations_separates_adjacent_citation_from_next_sentence() -> None:
    citation = Citation(
        index=1,
        chunk_id="c1",
        book_slug="nodes",
        section="HPA",
        anchor="hpa",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/nodes/index.html#hpa",
        excerpt="",
    )

    finalized, _, _ = finalize_citations(
        "답변: HPA는 Pod 에 지표를 확인합니다. [1]이 과정에서 설정을 확인합니다 [1].",
        [citation],
    )

    assert "Pod에" in finalized
    assert "[1] 이 과정" in finalized
    assert finalized.endswith("확인합니다. [1]")


def test_finalize_citations_preserves_section_numbers_and_sentence_spacing() -> None:
    citation = Citation(
        index=1,
        chunk_id="c1",
        book_slug="nodes",
        section="HPA",
        anchor="hpa",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/nodes/index.html#hpa",
        excerpt="",
    )

    finalized, _, _ = finalize_citations(
        "답변: 5.1.4. 절차입니다 [1]. HPA는 `metrics.k8s.io` 를 사용합니다.이때 Pod 에 requests가 필요합니다 [1].",
        [citation],
    )

    assert "5.1.4." in finalized
    assert "`metrics.k8s.io`를" in finalized
    assert "합니다. 이때 Pod에" in finalized


def test_shape_crash_loop_troubleshooting_returns_actionable_steps() -> None:
    citation = Citation(
        index=1,
        chunk_id="support--crashloop",
        book_slug="support",
        section="애플리케이션 진단 데이터 수집",
        anchor="diagnostic",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/support/index.html#diagnostic",
        excerpt="CrashLoopBackOff 상태에서는 describe와 logs로 진단 데이터를 수집합니다.",
        cli_commands=("oc describe pod/my-app-1-akdlg", "oc logs -f pod/my-app-1-akdlg"),
        verification_hints=("oc describe pod/my-app-1-akdlg", "oc logs -f pod/my-app-1-akdlg"),
    )

    answer = shape_crash_loop_troubleshooting(
        "답변: 먼저 문서를 여세요. [1]",
        query="CrashLoopBackOff는 어디부터 봐야해?",
        citations=[citation],
    )
    finalized, _, _ = finalize_citations(answer, [citation])

    assert "CrashLoopBackOff" in finalized
    assert "oc describe pod/my-app-1-akdlg" in finalized
    assert "oc logs -f pod/my-app-1-akdlg" in finalized
    assert "문서를 여세요" not in finalized


def test_strip_ungrounded_code_blocks_when_citation_has_no_commands() -> None:
    citation = Citation(
        index=1,
        chunk_id="runtime",
        book_slug="installation_overview",
        section="Runtimes",
        anchor="runtime",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/installation_overview/index.html#runtime",
        excerpt="CRI-O를 사용하여 런타임을 관리합니다.",
    )

    answer = strip_ungrounded_code_blocks(
        "답변: 먼저 확인합니다. [1]\n\n```bash\ncrio inspect <container-id>\n```",
        citations=[citation],
    )

    assert "crio inspect" not in answer
    assert "제공된 근거에는 실행 명령이나 예시 코드가 명시되어 있지 않습니다." in answer


def test_strip_ungrounded_code_blocks_when_citation_has_different_commands() -> None:
    citation = Citation(
        index=1,
        chunk_id="etcd-restore",
        book_slug="etcd",
        section="restore",
        anchor="restore",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/etcd/index.html#restore",
        excerpt="restore state",
        cli_commands=("oc adm wait-for-stable-cluster",),
    )

    answer = strip_ungrounded_code_blocks(
        "답변: 백업 명령입니다. [1]\n\n```bash\netcdctl snapshot save\n```",
        citations=[citation],
    )

    assert "etcdctl snapshot save" not in answer
    assert "oc adm wait-for-stable-cluster" not in answer


def test_scc_question_prefers_scc_answer_over_generic_can_i() -> None:
    citation = Citation(
        index=1,
        chunk_id="auth--scc",
        book_slug="authentication_and_authorization",
        section="SecurityContextConstraints",
        anchor="scc",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/authentication_and_authorization/index.html#scc",
        excerpt="SecurityContextConstraints(SCC)는 Pod가 사용할 수 있는 보안 컨텍스트를 제어합니다.",
        cli_commands=("oc adm policy who-can use scc/<scc-name>",),
    )

    answer = build_grounded_command_guide_answer(
        query="Pod가 권한 문제로 안 뜰 때 SCC 문제인지 어떻게 확인해?",
        citations=[citation],
    )

    assert answer is not None
    assert "SCC(SecurityContextConstraints)" in answer
    assert "oc adm policy who-can use scc/<scc-name>" in answer
    assert "oc auth can-i delete pods" not in answer


def test_serviceaccount_question_returns_rolebinding_flow() -> None:
    citation = Citation(
        index=1,
        chunk_id="auth--rolebinding-serviceaccount",
        book_slug="authentication_and_authorization",
        section="RoleBinding",
        anchor="rolebinding",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/authentication_and_authorization/index.html#rolebinding",
        excerpt="RoleBinding subjects can reference a ServiceAccount.",
        cli_commands=("oc describe rolebinding <rolebinding-name> -n <namespace>",),
    )

    answer = build_grounded_command_guide_answer(
        query="ServiceAccount 권한 문제를 RoleBinding 기준으로 어떻게 좁혀?",
        citations=[citation],
    )

    assert answer is not None
    assert "ServiceAccount" in answer
    assert "RoleBinding" in answer
    assert "system:serviceaccount:<namespace>:<serviceaccount>" in answer


def test_previous_logs_question_returns_previous_option() -> None:
    citation = Citation(
        index=1,
        chunk_id="support--logs-previous",
        book_slug="support",
        section="Pod logs",
        anchor="pod-logs",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/support/index.html#pod-logs",
        excerpt="Use oc logs --previous to view previous container logs.",
        cli_commands=("oc logs <pod-name> --previous",),
    )

    answer = build_grounded_command_guide_answer(
        query="재시작한 컨테이너의 이전 로그를 봐야 하면 어떤 옵션이야?",
        citations=[citation],
    )

    assert answer is not None
    assert "oc logs <pod-name> -n <namespace> --previous" in answer
    assert "-c <container-name>" in answer


def test_events_question_returns_namespace_sorted_events() -> None:
    citation = Citation(
        index=1,
        chunk_id="nodes--events",
        book_slug="nodes",
        section="Events",
        anchor="events",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/nodes/index.html#events",
        excerpt="Events show recent resource status changes.",
        cli_commands=("oc get events -n <namespace> --sort-by=.lastTimestamp",),
    )

    answer = build_grounded_command_guide_answer(
        query="최근 이벤트를 namespace 기준으로 확인하려면 어떤 명령이야?",
        citations=[citation],
    )

    assert answer is not None
    assert "oc get events -n <namespace> --sort-by=.lastTimestamp" in answer
    assert "oc describe <kind>/<name> -n <namespace>" in answer


def test_clusteroperator_status_question_returns_clusteroperators_command() -> None:
    citation = Citation(
        index=1,
        chunk_id="updating--clusteroperators",
        book_slug="updating_clusters",
        section="ClusterOperator status",
        anchor="clusteroperators",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/updating_clusters/index.html#clusteroperators",
        excerpt="ClusterOperator conditions include Available, Progressing, and Degraded.",
        cli_commands=("oc get clusteroperators",),
    )

    answer = build_grounded_command_guide_answer(
        query="ClusterOperator가 Degraded일 때 전체 상태를 한 번에 보는 명령은?",
        citations=[citation],
    )

    assert answer is not None
    assert "oc get clusteroperators" in answer
    assert "oc describe clusteroperator <operator-name>" in answer


def test_project_view_role_answer_stays_namespace_scoped() -> None:
    citation = Citation(
        index=1,
        chunk_id="auth--view-rolebinding",
        book_slug="authentication_and_authorization",
        section="로컬 역할 및 바인딩 보기",
        anchor="viewing-local-roles",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/authentication_and_authorization/index.html#viewing-local-roles",
        excerpt="다른 프로젝트에 대한 로컬 역할 바인딩을 보려면 -n 플래그를 추가합니다.",
        cli_commands=("oc describe rolebinding.rbac -n joe-project",),
    )

    answer = build_grounded_command_guide_answer(
        query="개발자에게 특정 프로젝트 view 권한만 주려면 어떤 식으로 줘?",
        citations=[citation],
    )

    assert answer is not None
    assert "oc adm policy add-role-to-user <role> <user> -n <project>" in answer
    assert "`<role>` 자리에 `view`" in answer
    assert "cluster-admin" not in answer


def test_route_timeout_answer_mentions_route_object() -> None:
    citation = Citation(
        index=1,
        chunk_id="route--timeout",
        book_slug="ingress_and_load_balancing",
        section="경로 시간 초과 구성",
        anchor="route-timeout",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/ingress_and_load_balancing/index.html#route-timeout",
        excerpt="Route timeout can be configured for a route.",
    )

    answer = build_grounded_command_guide_answer(
        query="Route timeout이 의심될 때 어느 설정을 먼저 봐야 해?",
        citations=[citation],
    )

    assert answer is not None
    assert "Route timeout" in answer
    assert "oc get route <route-name> -n <namespace> -o yaml" in answer


def test_registry_policy_answer_mentions_allowed_registries() -> None:
    citation = Citation(
        index=1,
        chunk_id="images--allowed-registries",
        book_slug="images",
        section="허용 목록에 특정 레지스트리 추가",
        anchor="allowed-registries",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/images/index.html#allowed-registries",
        excerpt="allowedRegistries can restrict which registry hosts are allowed.",
    )

    answer = build_grounded_command_guide_answer(
        query="허용된 registry만 쓰도록 제한하는 설정은 어디서 확인해?",
        citations=[citation],
    )

    assert answer is not None
    assert "allowedRegistries" in answer
    assert "oc get image.config.openshift.io/cluster -o yaml" in answer


def test_service_route_answer_checks_service_endpoints() -> None:
    citation = Citation(
        index=1,
        chunk_id="route--service",
        book_slug="ingress_and_load_balancing",
        section="경로를 생성하여 서비스 노출",
        anchor="service-route",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/ingress_and_load_balancing/index.html#service-route",
        excerpt="서비스가 노출되었는지 확인하려면 Route와 Service를 확인합니다.",
        cli_commands=("oc get route",),
    )

    answer = build_grounded_command_guide_answer(
        query="서비스는 있는데 Route 접속이 안 될 때 service endpoint부터 어떻게 확인해?",
        citations=[citation],
    )

    assert answer is not None
    assert "Service endpoint" in answer
    assert "oc get endpoints <service-name> -n <namespace>" in answer


def test_pvc_pending_answer_mentions_storageclass() -> None:
    citation = Citation(
        index=1,
        chunk_id="storage--pvc",
        book_slug="storage",
        section="PVC 상태 확인",
        anchor="pvc",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/storage/index.html#pvc",
        excerpt="PVC and StorageClass events explain why a PersistentVolumeClaim is Pending.",
        cli_commands=("oc describe pvc <pvc-name> -n <namespace>",),
    )

    answer = build_grounded_command_guide_answer(
        query="PVC가 Pending이면 StorageClass와 이벤트 중 무엇부터 봐야 해?",
        citations=[citation],
    )

    assert answer is not None
    assert "PVC가 Pending" in answer
    assert "oc get storageclass" in answer


def test_finalizer_answer_mentions_metadata_finalizers() -> None:
    citation = Citation(
        index=1,
        chunk_id="support--finalizer",
        book_slug="support",
        section="Namespace Terminating",
        anchor="finalizer",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/support/index.html#finalizer",
        excerpt="finalizer entries can keep a namespace in Terminating.",
        cli_commands=("oc get namespace <namespace> -o yaml",),
    )

    answer = build_grounded_command_guide_answer(
        query="namespace가 Terminating에서 안 없어지면 finalizer와 남은 리소스를 어떻게 확인해?",
        citations=[citation],
    )

    assert answer is not None
    assert "metadata.finalizers" in answer
