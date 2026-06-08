from __future__ import annotations

import play_book_studio.answering.context as answer_context
from play_book_studio.answering.context import assemble_context
from play_book_studio.retrieval.models import RetrievalHit, SessionContext


def test_assemble_context_preserves_section_metadata_on_citations() -> None:
    hit = RetrievalHit(
        chunk_id="chunk-1",
        book_slug="study-pods",
        chapter="Workloads",
        section="Pods",
        anchor="pods",
        source_url="corpus/sources/kmsc/raw/pod-guide.pdf",
        viewer_path="/uploads/documents/source-1/chunks/chunk-1",
        text="Use oc get pods to inspect pod status.",
        source="vector",
        raw_score=0.9,
        section_path=("Workloads", "Pods"),
        section_number="1.2",
        heading_title="Pods",
        source_anchor="pods",
        toc_path=("1 Workloads", "1.2 Pods"),
        asset_ids=("asset-a", "asset-b"),
        learning={
            "refs": {
                "next_refs": [
                    {"ref_type": "document", "book_slug": "deployments", "reason": "다음 학습 단계"}
                ]
            }
        },
    )

    bundle = assemble_context([hit], query="pod status", max_chunks=1)

    citation = bundle.citations[0]
    assert citation.section_number == "1.2"
    assert citation.heading_title == "Pods"
    assert citation.source_anchor == "pods"
    assert citation.toc_path == ("1 Workloads", "1.2 Pods")
    assert citation.asset_ids == ("asset-a", "asset-b")
    assert citation.learning["refs"]["next_refs"][0]["book_slug"] == "deployments"
    assert "learning_next_refs:" in bundle.prompt_context
    assert "- deployments: 다음 학습 단계" in bundle.prompt_context
    assert citation.to_dict()["toc_path"] == ("1 Workloads", "1.2 Pods")
    assert citation.to_dict()["asset_id"] == "asset-a"


def test_assemble_context_strips_internal_code_markup_from_citations() -> None:
    hit = RetrievalHit(
        chunk_id="chunk-code",
        book_slug="cli-tools",
        chapter="CLI",
        section="2.6.1.78. oc get",
        anchor="oc-get",
        source_url="https://example.test/cli",
        viewer_path="/docs/cli",
        text='Before running it. [CODE language="shell-session"] $ oc get pods -n demo [/CODE] Then inspect status.',
        source="vector",
        raw_score=1.0,
        cli_commands=('[CODE] oc get pods -n demo [/CODE]',),
    )

    bundle = assemble_context([hit], query="pod 확인 명령어", max_chunks=1)
    citation = bundle.citations[0]

    assert "[CODE" not in citation.excerpt
    assert "[/CODE]" not in citation.excerpt
    assert citation.cli_commands == ("oc get pods -n demo",)
    assert citation.section == "oc get"


def test_assemble_context_drops_polluted_unrelated_cli_commands() -> None:
    hit = RetrievalHit(
        chunk_id="chunk-pvc",
        book_slug="storage",
        chapter="Storage",
        section="PVC Pending",
        anchor="pvc-pending",
        source_url="https://example.test/storage",
        viewer_path="/docs/storage",
        text=(
            "PVC가 Pending 상태인지 확인합니다.\n\n"
            "```shell\n$ oc get pvc -n <namespace>\n```\n\n"
            "출력 예\nNAME STATUS VOLUME\nclaim Bound pvc-123"
        ),
        source="vector",
        raw_score=1.0,
        cli_commands=(
            "oc\n[/CODE]",
            "oc create -f <file_name> -n <application_namespace>",
            "oc get pvc -n <namespace>",
        ),
    )

    bundle = assemble_context([hit], query="PVC가 Pending인데 뭐 확인해야 해?", max_chunks=1)
    citation = bundle.citations[0]

    assert citation.cli_commands == ("oc get pvc -n <namespace>",)
    assert "oc create -f" not in bundle.prompt_context
    assert "\noc\n" not in bundle.prompt_context


def test_assemble_context_trims_command_output_examples() -> None:
    hit = RetrievalHit(
        chunk_id="chunk-pvc-output",
        book_slug="storage",
        chapter="Storage",
        section="PVC Pending",
        anchor="pvc-pending",
        source_url="https://example.test/storage",
        viewer_path="/docs/storage",
        text=(
            "PVC 상태는 다음 명령으로 확인합니다.\n"
            "[CODE]oc get pvc -n <namespace>[/CODE]\n"
            "출력 예\n"
            "NAME STATUS VOLUME CAPACITY ACCESS MODES STORAGECLASS AGE\n"
            "data Pending"
        ),
        source="vector",
        raw_score=1.0,
    )

    bundle = assemble_context([hit], query="PVC가 Pending인데 뭐 확인해야 해?", max_chunks=1)
    citation = bundle.citations[0]

    assert citation.cli_commands == ("oc get pvc -n <namespace>",)
    assert "oc get pvc -n <namespace> 출력 예" not in bundle.prompt_context


def test_assemble_context_demotes_navigation_only_hits() -> None:
    nav_hit = RetrievalHit(
        chunk_id="chunk-nav",
        book_slug="installing_on_any_platform",
        chapter="Install",
        section="Waiting",
        anchor="waiting",
        source_url="https://example.test/nav",
        viewer_path="/docs/nav",
        text="관련 문서\nOpen document\nClose\n다음 문서",
        source="vector",
        raw_score=1.0,
    )
    content_hit = RetrievalHit(
        chunk_id="chunk-content",
        book_slug="installing_on_any_platform",
        chapter="Install",
        section="Bootstrap",
        anchor="bootstrap",
        source_url="https://example.test/bootstrap",
        viewer_path="/docs/bootstrap",
        text="Bootstrap이 완료될 때까지 openshift-install wait-for bootstrap-complete 명령으로 상태를 확인한다.",
        source="vector",
        raw_score=0.8,
    )

    bundle = assemble_context([nav_hit, content_hit], query="bootstrap 상태 확인", max_chunks=1)

    assert bundle.citations[0].chunk_id == "chunk-content"


def test_assemble_context_keeps_multiple_user_upload_hits_for_active_document() -> None:
    service_hit = RetrievalHit(
        chunk_id="chunk-service",
        book_slug="uploaded-documents",
        chapter="네트워킹",
        section="Service",
        anchor="service",
        source_url="uploads/source.pdf",
        viewer_path="/uploads/documents/doc-a/index.html#service",
        text="Service는 Pod 집합에 대한 네트워크 접근을 추상화한다.",
        source="hybrid",
        raw_score=1.0,
        fused_score=0.057,
        document_source_id="doc-a",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
        source_collection="uploads",
    )
    type_hit = RetrievalHit(
        chunk_id="chunk-types",
        book_slug="uploaded-documents",
        chapter="네트워킹",
        section="타입",
        anchor="types",
        source_url="uploads/source.pdf",
        viewer_path="/uploads/documents/doc-a/index.html#types",
        text="NodePort는 외부에서 Node의 특정 포트로 접근하고, LoadBalancer는 클라우드 외부 로드밸런서를 생성한다.",
        source="hybrid",
        raw_score=1.0,
        fused_score=0.046,
        document_source_id="doc-a",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
        source_collection="uploads",
    )

    bundle = assemble_context(
        [service_hit, type_hit],
        query="NodePort와 LoadBalancer 차이 설명",
        session_context=SessionContext(owner_user_id="owner-a", active_document_id="doc-a"),
        max_chunks=4,
    )

    assert [citation.chunk_id for citation in bundle.citations] == ["chunk-service", "chunk-types"]


def test_assemble_context_replaces_thin_user_upload_title_hit_with_substantive_chunk() -> None:
    title_hit = RetrievalHit(
        chunk_id="chunk-title",
        book_slug="uploaded-documents",
        chapter="CI 순서",
        section="CI 순서",
        anchor="ci-title",
        source_url="uploads/ci.pdf",
        viewer_path="/uploads/documents/doc-ci/index.html#chunk-title",
        text="CI 순서\n\nCI 순서",
        source="hybrid",
        raw_score=1.0,
        fused_score=0.06,
        section_path=("CI 순서",),
        heading_title="CI 순서",
        document_source_id="doc-ci",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
        source_collection="uploads",
    )
    body_hit = RetrievalHit(
        chunk_id="chunk-body",
        book_slug="uploaded-documents",
        chapter="CI 순서",
        section="git source에 파이프라인 yaml 구성",
        anchor="ci-body",
        source_url="uploads/ci.pdf",
        viewer_path="/uploads/documents/doc-ci/index.html#chunk-body",
        text=(
            "CI 순서 > git source에 파이프라인 yaml 구성\n\n"
            "Git push 이벤트가 들어오면 Tekton PipelineRun이 실행되고, "
            "이미지를 빌드한 뒤 레지스트리에 push합니다."
        ),
        source="hybrid",
        raw_score=0.8,
        fused_score=0.04,
        section_path=("CI 순서", "git source에 파이프라인 yaml 구성"),
        heading_title="git source에 파이프라인 yaml 구성",
        document_source_id="doc-ci",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
        source_collection="uploads",
    )

    bundle = assemble_context(
        [title_hit, body_hit],
        query="업로드 문서 기준 CI 순서 핵심을 알려줘",
        session_context=SessionContext(owner_user_id="owner-a", active_document_id="doc-ci"),
        max_chunks=1,
    )

    assert [citation.chunk_id for citation in bundle.citations] == ["chunk-body"]
    assert "Git push 이벤트" in bundle.citations[0].excerpt


def test_assemble_context_uses_db_companion_when_top_hits_only_have_upload_title(monkeypatch, tmp_path) -> None:
    title_hit = RetrievalHit(
        chunk_id="chunk-title",
        book_slug="uploaded-documents",
        chapter="CI 순서",
        section="CI 순서",
        anchor="ci-title",
        source_url="uploads/ci.pdf",
        viewer_path="/uploads/documents/doc-ci/index.html#chunk-title",
        text="CI 순서\n\nCI 순서",
        source="hybrid",
        raw_score=1.0,
        fused_score=0.06,
        section_path=("CI 순서",),
        heading_title="CI 순서",
        document_source_id="doc-ci",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
        source_collection="uploads",
    )
    db_body_hit = RetrievalHit(
        chunk_id="chunk-db-body",
        book_slug="uploaded-documents",
        chapter="CI 순서",
        section="git source에 파이프라인 yaml 구성",
        anchor="ci-db-body",
        source_url="uploads/ci.pdf",
        viewer_path="/uploads/documents/doc-ci/index.html#chunk-db-body",
        text="CI 순서 > git source에 파이프라인 yaml 구성\n\nPipelineRun이 이미지를 빌드하고 레지스트리에 push합니다.",
        source="hybrid",
        raw_score=0.05,
        fused_score=0.05,
        document_source_id="doc-ci",
        owner_user_id="owner-a",
        visibility="private_user",
        source_scope="user_upload",
        source_collection="uploads",
    )
    monkeypatch.setattr(
        answer_context,
        "_substantive_upload_companion_from_db",
        lambda target, root_dir, used_chunk_ids: db_body_hit,
    )

    bundle = assemble_context(
        [title_hit],
        query="업로드 문서 기준 CI 순서 핵심을 알려줘",
        session_context=SessionContext(owner_user_id="owner-a", active_document_id="doc-ci"),
        root_dir=tmp_path,
        max_chunks=1,
    )

    assert [citation.chunk_id for citation in bundle.citations] == ["chunk-db-body"]
    assert "PipelineRun" in bundle.citations[0].excerpt


def test_assemble_context_seeds_customer_data_for_completion_report_query() -> None:
    customer_hit = RetrievalHit(
        chunk_id="chunk-customer-completion",
        book_slug="kmsc-operations",
        chapter="완료보고",
        section="목표 기준 결과 : OCP 가용성 및 업무 테스트 정상 트랜잭션(200 User) 기준",
        anchor="completion-risk",
        source_url="uploads/completion.pptx",
        viewer_path="/uploads/documents/customer-doc/index.html#completion-risk",
        text="완료보고 완료본에는 WBS 진척률, 업무 테스트, 운영 준비 리스크, 서버/스토리지/Worker 준비 현황이 포함된다.",
        source="hybrid",
        raw_score=0.03,
        fused_score=0.237,
        source_scope="study_docs",
        source_collection="core",
        source_lane="study_docs",
    )
    official_hit = RetrievalHit(
        chunk_id="chunk-official-overview",
        book_slug="overview",
        chapter="개요",
        section="OpenShift Container Platform 소개",
        anchor="overview",
        source_url="docs/overview",
        viewer_path="/docs/ocp/4.20/ko/overview/index.html#overview",
        text="OpenShift Container Platform은 컨테이너 애플리케이션 플랫폼이다.",
        source="hybrid",
        raw_score=0.04,
        fused_score=0.255,
        source_scope="official_docs",
        source_collection="core",
    )

    bundle = assemble_context(
        [customer_hit, official_hit],
        query="완료보고서 기준으로 현재 OCP 운영 준비 리스크를 공식 운영 체크포인트와 같이 정리해줘",
        max_chunks=4,
    )

    assert bundle.citations[0].chunk_id == "chunk-customer-completion"
    assert bundle.citations[0].source_scope == "study_docs"
    assert bundle.citations[0].viewer_path.startswith("/uploads/documents/customer-doc/")
