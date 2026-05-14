from __future__ import annotations

from play_book_studio.answering.answer_text import shape_beginner_grounded_answer
from play_book_studio.answering.models import Citation
from play_book_studio.retrieval.query_understanding import understand_query


def _citation(**overrides) -> Citation:
    payload = {
        "index": 1,
        "chunk_id": "c1",
        "book_slug": "cli_tools",
        "section": "CLI commands",
        "anchor": "c1",
        "source_url": "",
        "viewer_path": "/docs/c1",
        "excerpt": "Use the OpenShift CLI to inspect the resource status and events.",
        "cli_commands": (),
    }
    payload.update(overrides)
    return Citation(**payload)


def test_readable_korean_queries_are_understood_without_fixed_answers() -> None:
    install = understand_query("OCP 설치 어떻게 해?")
    command = understand_query("네임스페이스 확인 명령어가 뭐야?")
    trouble = understand_query("Secret 컨피그가 계속 오류뜨는데 왜 이래?")

    assert "install_overview" in install.intents
    assert "command_lookup" in command.intents
    assert "namespace_or_project" in command.intents
    assert "troubleshooting" in trouble.intents
    assert "secret_config_troubleshooting" in trouble.intents


def test_beginner_install_answer_is_shaped_from_install_citations_not_specific_question() -> None:
    answer = shape_beginner_grounded_answer(
        "답변: 지금 질문은 현재 공식 문서 근거와 정확히 맞물리는 점수가 낮습니다.",
        query="OCP 설치 어떻게 해?",
        citations=[
            _citation(
                index=1,
                book_slug="installation_overview",
                section="OpenShift Container Platform installation overview",
                excerpt=(
                    "The OpenShift Container Platform installation program provides installation methods "
                    "including Assisted Installer, Agent-based Installer, installer-provisioned and "
                    "user-provisioned infrastructure. Single Node OpenShift is supported for single node deployments."
                ),
            ),
            _citation(
                index=2,
                book_slug="installing_on_any_platform",
                section="Waiting for the bootstrap process to complete",
                excerpt="Monitor the bootstrap process with openshift-install wait-for bootstrap-complete.",
                cli_commands=(
                    "openshift-install --dir <installation_directory> wait-for bootstrap-complete --log-level=info",
                ),
            ),
        ],
    )

    assert "정확히 맞물리는 점수가 낮" not in answer
    assert "Assisted Installer" in answer
    assert "Agent-based Installer" in answer
    assert "IPI" in answer
    assert "UPI" in answer
    assert "openshift-install" in answer
    assert "[1]" in answer


def test_beginner_command_answer_uses_grounded_commands_for_any_command_question() -> None:
    answer = shape_beginner_grounded_answer(
        "답변: 확인하면 됩니다.",
        query="네임스페이스 확인 명령어가 뭐야?",
        citations=[
            _citation(
                excerpt="Use oc project to view the current project. Use oc get namespaces to list namespaces.",
                cli_commands=("oc project -q", "oc get namespaces"),
            )
        ],
    )

    assert "명령어 확인 요청" in answer
    assert "oc project -q" in answer
    assert "oc get namespaces" in answer
    assert "```bash" in answer


def test_beginner_troubleshooting_answer_is_generic_intent_based() -> None:
    answer = shape_beginner_grounded_answer(
        "답변: 더 좁혀 주세요.",
        query="Secret 컨피그가 계속 오류뜨는데 왜 이래?",
        citations=[
            _citation(
                book_slug="applications",
                section="Troubleshooting application configuration",
                excerpt="Use oc describe pod to inspect events and verify Secret or ConfigMap volume and environment variable configuration.",
                cli_commands=("oc describe pod <pod-name> -n <namespace>", "oc get secret -n <namespace>"),
            )
        ],
    )

    assert "문제 원인을 좁히는 흐름" in answer
    assert "oc describe pod" in answer
    assert "Secret/ConfigMap" in answer
    assert "정상/비정상" in answer


def test_beginner_shape_does_not_override_strong_existing_answer() -> None:
    original = (
        "답변: 이미 충분히 구조화된 답변입니다.\n\n"
        "1. 설치 방식을 비교합니다.\n"
        "- Assisted Installer와 Agent-based Installer를 비교합니다.\n"
        "- Single Node OpenShift(SNO)는 서버 1대 실습/PoC 구성으로 봅니다.\n"
        "- installer-provisioned와 user-provisioned 흐름을 나눕니다.\n"
        "- openshift-install 명령으로 bootstrap 완료를 확인합니다.\n\n"
        "```bash\nopenshift-install --dir <installation_directory> wait-for bootstrap-complete --log-level=info\n```"
    )

    answer = shape_beginner_grounded_answer(
        original,
        query="OCP 설치 어떻게 해?",
        citations=[
            _citation(
                book_slug="installation_overview",
                excerpt="Assisted Installer, Agent-based Installer, installer-provisioned and user-provisioned installation.",
                cli_commands=("openshift-install --dir <installation_directory> wait-for bootstrap-complete --log-level=info",),
            )
        ],
    )

    assert answer == original


def test_beginner_namespace_create_answer_adds_project_and_namespace_commands() -> None:
    answer = shape_beginner_grounded_answer(
        "요약: 프로젝트를 만들면 됩니다.",
        query="특정 namespace를 만드는 명령어가 뭐야?",
        citations=[
            _citation(
                excerpt="Use the OpenShift CLI to create projects and namespaces.",
                cli_commands=("oc new-project <project-name>", "oc create namespace <namespace-name>"),
            )
        ],
    )

    assert "oc new-project <project-name>" in answer
    assert "oc create namespace <namespace-name>" in answer
    assert "oc get namespaces" in answer
    assert "판단 기준" in answer


def test_beginner_deployment_answer_adds_manifest_and_apply_flow() -> None:
    answer = shape_beginner_grounded_answer(
        "요약: YAML을 작성하면 됩니다.",
        query="보통 배포 yaml파일은 어케 작성하지?",
        citations=[
            _citation(
                book_slug="building_applications",
                excerpt="Create a Deployment manifest and apply it with the OpenShift CLI.",
                cli_commands=("oc apply -f deployment.yaml", "oc rollout status deployment/example-app"),
            )
        ],
    )

    assert "kind: Deployment" in answer
    assert "oc apply -f deployment.yaml" in answer
    assert "oc rollout status deployment/example-app" in answer


def test_beginner_service_failure_answer_adds_endpoint_route_diagnosis() -> None:
    answer = shape_beginner_grounded_answer(
        "요약: 서비스를 확인하세요.",
        query="Service쪽에서 계속 장애나는데 뭐가 원인일까?",
        citations=[
            _citation(
                book_slug="networking",
                excerpt="A Service uses selectors and endpoints. Routes expose services.",
                cli_commands=("oc describe service <service-name>", "oc get endpoints <service-name>"),
            )
        ],
    )

    assert "Service 장애" in answer
    assert "Endpoint" in answer
    assert "Route" in answer
    assert "selector" in answer
    assert "targetPort" in answer


def test_beginner_pod_resource_answer_adds_top_pods_flow() -> None:
    answer = shape_beginner_grounded_answer(
        "요약: 리소스를 확인하세요.",
        query="특정 Pod의 리소스가 얼마나 잡아먹고 있는지 확인하는 법",
        citations=[
            _citation(
                book_slug="nodes",
                excerpt="Use metrics to inspect pod CPU and memory resource usage.",
                cli_commands=("oc adm top pods -n <namespace>",),
            )
        ],
    )

    assert "oc adm top pod --namespace=<namespace>" in answer
    assert "CPU" in answer
    assert "memory" in answer
    assert "metrics" in answer


def test_beginner_deployment_command_answer_replaces_generic_apply_answer() -> None:
    answer = shape_beginner_grounded_answer(
        "답변: 실행 예시는 아래 명령을 기준으로 보면 됩니다.\n\n```bash\noc apply -f <your_data_gather_definition>.yaml\n```",
        query="ocp에서 배포를 하고 싶으면 무슨 명령어로 해야되더라?",
        citations=[
            _citation(
                book_slug="support",
                excerpt="Use oc apply -f to apply a YAML resource definition.",
                cli_commands=("oc apply -f <your_data_gather_definition>.yaml",),
            )
        ],
    )

    assert "Deployment" in answer
    assert "oc apply -f deployment.yaml" in answer
    assert "oc rollout status deployment/<name>" in answer
