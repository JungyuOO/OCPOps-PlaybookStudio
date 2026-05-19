from __future__ import annotations

from play_book_studio.answering.context import assemble_context
from play_book_studio.answering.answerer import _is_low_confidence_retrieval
from play_book_studio.answering.answer_text_commands import strip_ungrounded_code_blocks
from play_book_studio.answering.answer_text_formatting import shape_beginner_grounded_answer
from play_book_studio.answering.models import AnswerResult, Citation
from play_book_studio.http.presenters import _citation_display_payload
from play_book_studio.http.session_flow import dedupe_suggestions, suggest_follow_up_questions
from play_book_studio.http.sessions import ChatSession
from play_book_studio.evals.studio_live_smoke import SmokeCase, _validate_case
from play_book_studio.retrieval.models import RetrievalHit, SessionContext
from play_book_studio.retrieval.query import has_command_request
from play_book_studio.retrieval.scoring import fuse_ranked_hits


def _hit(
    chunk_id: str,
    *,
    text: str,
    cli_commands: tuple[str, ...] = (),
    error_strings: tuple[str, ...] = (),
    k8s_objects: tuple[str, ...] = (),
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
        error_strings=error_strings,
        k8s_objects=k8s_objects,
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


def test_vsphere_dynamic_storage_query_prefers_vsphere_pvc_chunk_over_azure() -> None:
    azure_hit = _hit(
        "azure-file",
        text="Azure File 정적 프로비저닝 절차입니다. oc create -f azure-file-pv.yaml",
        cli_commands=("oc create -f azure-file-pv.yaml",),
        k8s_objects=("PV", "PVC"),
        chunk_type="procedure",
        book_slug="storage",
        section="Azure File의 정적 프로비저닝",
        raw_score=0.34,
    )
    vsphere_hit = _hit(
        "vsphere-pvc",
        text=(
            "CLI를 사용하여 VMware vSphere 볼륨을 동적으로 프로비저닝합니다. "
            "기본 StorageClass thin을 사용하고 pvc.yaml 파일을 만든 후 oc create -f pvc.yaml 명령을 실행합니다."
        ),
        cli_commands=("oc create -f pvc.yaml",),
        k8s_objects=("PVC", "StorageClass"),
        chunk_type="procedure",
        book_slug="storage",
        section="CLI를 사용하여 VMware vSphere 볼륨을 동적으로 프로비저닝",
        raw_score=0.22,
    )

    hits = fuse_ranked_hits(
        "vSphere에서 PVC로 볼륨을 동적 프로비저닝하려면 어떻게 해?",
        {"bm25": [azure_hit, vsphere_hit]},
        context=SessionContext(),
        top_k=2,
    )

    assert hits[0].chunk_id == "vsphere-pvc"
    assert hits[0].component_scores["vsphere_storage_match_boost"] == 2.2
    assert hits[0].component_scores["vsphere_dynamic_provisioning_boost"] == 1.65
    assert "vsphere_storage_cloud_mismatch_penalty" in hits[1].component_scores


def test_vsphere_static_storage_query_prefers_static_pv_pvc_chunk() -> None:
    dynamic_hit = _hit(
        "vsphere-dynamic",
        text="VMware vSphere 볼륨을 동적으로 프로비저닝합니다. pvc.yaml 파일과 thin-csi StorageClass를 사용합니다.",
        cli_commands=("oc create -f pvc.yaml",),
        k8s_objects=("PVC", "StorageClass"),
        chunk_type="procedure",
        book_slug="storage",
        raw_score=0.34,
    )
    static_hit = _hit(
        "vsphere-static",
        text=(
            "정적으로 프로비저닝 VMware vSphere 볼륨 절차입니다. "
            "pv1.yaml 및 pvc1.yaml 파일을 만들고 oc create -f pv1.yaml, oc create -f pvc1.yaml 명령을 실행합니다."
        ),
        cli_commands=("oc create -f pv1.yaml", "oc create -f pvc1.yaml"),
        k8s_objects=("PV", "PVC"),
        chunk_type="procedure",
        book_slug="storage",
        raw_score=0.24,
    )

    hits = fuse_ranked_hits(
        "vSphere 볼륨을 정적으로 연결하려면 어떤 리소스를 만들어야 해?",
        {"bm25": [dynamic_hit, static_hit]},
        context=SessionContext(),
        top_k=2,
    )

    assert hits[0].chunk_id == "vsphere-static"
    assert hits[0].component_scores["vsphere_static_provisioning_boost"] == 1.72
    assert "vsphere_static_dynamic_mismatch_penalty" in hits[1].component_scores


def test_vsphere_storage_citation_does_not_trigger_low_confidence_clarification() -> None:
    citation = Citation(
        index=1,
        chunk_id="vsphere-pvc",
        book_slug="storage",
        section="CLI를 사용하여 VMware vSphere 볼륨을 동적으로 프로비저닝",
        anchor="vsphere-pvc",
        source_url="",
        viewer_path="/docs/storage#vsphere-pvc",
        excerpt="VMware vSphere PersistentVolumeClaim을 pvc.yaml로 정의하고 oc create -f pvc.yaml 명령을 실행합니다.",
        cli_commands=("oc create -f pvc.yaml",),
        k8s_objects=("PVC", "StorageClass"),
    )

    assert not _is_low_confidence_retrieval(
        query="vSphere에서 PVC로 볼륨을 동적 프로비저닝하려면 어떻게 해?",
        citations=[citation],
        selected_hits=[{"fused_score": 0.01, "pre_rerank_fused_score": 0.01, "vector_score": 0.01}],
    )


def test_v014_structured_signals_boost_matching_pvc_pending_troubleshooting_chunk() -> None:
    concept_hit = _hit(
        "storage-concept",
        text="Persistent storage concepts describe volume binding and provisioning.",
        book_slug="storage",
        raw_score=0.31,
    )
    troubleshooting_hit = _hit(
        "pvc-pending",
        text="PVC Pending 상태에서는 PVC 이벤트와 StorageClass 바인딩 상태를 확인합니다.",
        cli_commands=("oc get pvc", "oc describe pvc <pvc-name> -n <namespace>",),
        error_strings=("Pending",),
        k8s_objects=("PVC", "StorageClass"),
        chunk_type="troubleshooting",
        book_slug="storage",
        raw_score=0.29,
    )

    hits = fuse_ranked_hits(
        "PVC가 Pending이면 뭐부터 확인해야 해?",
        {"bm25": [concept_hit, troubleshooting_hit]},
        context=SessionContext(),
        top_k=2,
    )

    assert hits[0].chunk_id == "pvc-pending"
    assert "v014_object_signal_boost" not in hits[0].component_scores
    assert "v014_error_state_signal_boost" not in hits[0].component_scores
    assert "v014_answer_shape_chunk_boost" not in hits[0].component_scores


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


def test_follow_up_questions_do_not_invent_failure_diagnostics_for_procedure_only_command() -> None:
    result = AnswerResult(
        query="kubeadmin 사용자를 제거하려면 어떻게 해?",
        mode="chat",
        answer="답변: `oc delete secrets kubeadmin -n kube-system` 명령으로 제거합니다 [1].",
        rewritten_query="kubeadmin 사용자를 제거하려면 어떻게 해?",
        response_kind="rag",
        citations=[
            Citation(
                index=1,
                chunk_id="kubeadmin-remove",
                book_slug="authentication_and_authorization",
                section="kubeadmin 사용자 제거",
                anchor="kubeadmin-remove",
                source_url="",
                viewer_path="/docs/kubeadmin-remove",
                excerpt="kubeadmin 사용자를 제거하려면 kubeadmin secret을 삭제합니다.",
                cli_commands=("oc delete secrets kubeadmin -n kube-system",),
            )
        ],
        cited_indices=[1],
    )

    suggestions = suggest_follow_up_questions(session=ChatSession(session_id="s1"), result=result)

    assert suggestions
    assert not any("실패하면" in suggestion for suggestion in suggestions)
    assert not any("어떤 근거" in suggestion for suggestion in suggestions)
    assert any("주의" in suggestion or "제거" in suggestion for suggestion in suggestions)


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


def test_v016_aws_registry_storage_penalizes_rhosp_chunks() -> None:
    rhosp_hit = _hit(
        "rhosp-cinder",
        text="RHOSP OpenStack Cinder volume can be used for image registry storage.",
        book_slug="registry",
        section="RHOSP image registry storage",
        raw_score=0.42,
    )
    aws_hit = _hit(
        "aws-s3",
        text="AWS user-provisioned clusters configure image registry storage with S3 bucket settings.",
        book_slug="registry",
        section="AWS user-provisioned image registry storage",
        raw_score=0.28,
    )

    hits = fuse_ranked_hits(
        "AWS 사용자 프로비저닝 환경에서 레지스트리 스토리지는 어떻게 설정해?",
        {"bm25": [rhosp_hit, aws_hit]},
        context=SessionContext(),
        top_k=2,
    )

    assert hits[0].chunk_id == "aws-s3"
    assert hits[0].component_scores["v016_aws_registry_storage_platform_boost"] == 1.9
    assert "v016_aws_registry_storage_platform_mismatch_penalty" in hits[1].component_scores


def test_v016_etcd_defrag_penalizes_disk_only_commands() -> None:
    disk_hit = _hit(
        "disk-lsblk",
        text="Use oc debug node/<node-name> -- chroot /host lsblk to inspect disks.",
        cli_commands=("oc debug node/<node-name> -- chroot /host lsblk",),
        book_slug="nodes",
        raw_score=0.42,
    )
    defrag_hit = _hit(
        "etcd-defrag",
        text="Run etcdctl defrag from an etcdctl container to perform manual etcd defragmentation.",
        cli_commands=("etcdctl defrag",),
        book_slug="etcd",
        section="Manual etcd defragmentation",
        raw_score=0.24,
    )

    hits = fuse_ranked_hits(
        "etcd 수동 조각 모음은 어떤 명령어로 진행해?",
        {"bm25": [disk_hit, defrag_hit]},
        context=SessionContext(),
        top_k=2,
    )

    assert hits[0].chunk_id == "etcd-defrag"
    assert hits[0].component_scores["v016_etcd_defrag_boost"] == 2.1
    assert "v016_etcd_defrag_disk_command_penalty" in hits[1].component_scores


def test_v016_insights_query_penalizes_operator_catalog_chunks() -> None:
    catalog_hit = _hit(
        "catalog",
        text="Use oc get catalogsource to inspect an Operator catalog source.",
        cli_commands=("oc get catalogsource",),
        book_slug="operators",
        raw_score=0.38,
    )
    insights_hit = _hit(
        "insights",
        text="The Insights Operator runs in openshift-insights and creates archives for remote health reporting.",
        cli_commands=("oc get pods -n openshift-insights",),
        book_slug="support",
        section="Insights Operator archive",
        raw_score=0.26,
    )

    hits = fuse_ranked_hits(
        "Insights Operator 아카이브는 어떻게 업로드해?",
        {"bm25": [catalog_hit, insights_hit]},
        context=SessionContext(),
        top_k=2,
    )

    assert hits[0].chunk_id == "insights"
    assert hits[0].component_scores["v016_insights_support_boost"] == 1.8
    assert "v016_insights_operator_catalog_penalty" in hits[1].component_scores


def test_v016_build_input_security_penalizes_oauth_chunks() -> None:
    oauth_hit = _hit(
        "oauth",
        text="Configure OAuth OIDC authentication.config/cluster with a client secret.",
        cli_commands=("oc edit authentication.config/cluster",),
        book_slug="authentication",
        raw_score=0.4,
    )
    build_hit = _hit(
        "build-secret",
        text="BuildConfig can use a source secret to secure build inputs.",
        cli_commands=("oc set build-secret --source bc/my-build my-secret",),
        book_slug="builds",
        section="Build input secrets",
        raw_score=0.27,
    )

    hits = fuse_ranked_hits(
        "빌드 입력 보안을 적용하려면 어떤 명령어를 써?",
        {"bm25": [oauth_hit, build_hit]},
        context=SessionContext(),
        top_k=2,
    )

    assert hits[0].chunk_id == "build-secret"
    assert hits[0].component_scores["v016_build_input_security_boost"] == 1.8
    assert "v016_build_input_oauth_penalty" in hits[1].component_scores


def test_v016_route_admission_policy_penalizes_expose_route_chunks() -> None:
    expose_hit = _hit(
        "route-expose",
        text="Expose a service as a route with oc expose service nodejs-ex and verify with oc get route.",
        cli_commands=("oc expose service nodejs-ex", "oc get route"),
        book_slug="networking",
        raw_score=0.4,
    )
    admission_hit = _hit(
        "route-admission",
        text="Configure routeAdmission namespaceOwnership InterNamespaceAllowed on the default IngressController.",
        cli_commands=(
            "oc -n openshift-ingress-operator patch ingresscontroller/default --patch '{\"spec\":{\"routeAdmission\":{\"namespaceOwnership\":\"InterNamespaceAllowed\"}}}' --type=merge",
        ),
        book_slug="ingress",
        section="Route admission policy",
        raw_score=0.25,
    )

    hits = fuse_ranked_hits(
        "Route 허용 정책은 어떻게 설정해?",
        {"bm25": [expose_hit, admission_hit]},
        context=SessionContext(),
        top_k=2,
    )

    assert hits[0].chunk_id == "route-admission"
    assert hits[0].component_scores["v016_route_admission_policy_boost"] == 2.0
    assert "v016_route_expose_policy_mismatch_penalty" in hits[1].component_scores
