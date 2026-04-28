from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


AUDIT_SCHEMA = "ops_learning_anchor_audit_v1"
GUIDE_SCHEMA = "ops_learning_guide_v1"
GOLDEN_CASE_SCHEMA = "ops_learning_golden_case_v1"
LEARNING_CHUNK_SCHEMA = "ops_learning_chunk_v1"
DEFAULT_COURSE_DIR = Path("data/course_pbs")
DEFAULT_AUDIT_PATH = Path("data/course_pbs/manifests/ops_learning_anchor_audit_v1.json")
DEFAULT_GUIDES_PATH = Path("data/course_pbs/manifests/ops_learning_guides_v1.json")
DEFAULT_GOLDEN_PATH = Path("manifests/course_ops_learning_golden_cases.jsonl")
DEFAULT_LEARNING_CHUNKS_PATH = Path("data/course_pbs/manifests/ops_learning_chunks_v1.jsonl")
OPS_SEQUENCE_TEXT_LIMIT = 560
OPS_SOURCE_SUMMARY_TEXT_LIMIT = 500

SOURCE_ONLY_TITLES = {
    "목차",
    "contents",
    "index",
}
SOURCE_ONLY_TITLE_FRAGMENTS = (
    "완료본",
    "표지",
    "개정이력",
    "목차",
    "감사합니다",
)
STATEFUL_IMAGE_ROLES = {
    "command_result_evidence",
    "expected_state_indicator",
    "success_state",
    "failure_state",
    "progress_state",
    "console_output",
    "dashboard_metric",
    "ui_navigation_evidence",
}
INTERNAL_ID_RE = re.compile(r"\b(?:DSGN|TEST|CH|KMSC|OCP|PERF|ITG)[-A-Z0-9]*", re.I)


INITIAL_GUIDE_DEFINITIONS: list[dict[str, Any]] = [
    {
        "guide_id": "architecture_overview",
        "stage_id": "architecture",
        "title": "OpenShift 운영 아키텍처 큰 흐름",
        "learning_goal": "외부, DMZ, 내부망, DB, 스토리지, 모니터링 영역을 운영 관점에서 먼저 잡는다.",
        "next_guide_id": "service_flow_network_reading",
        "steps": [
            {
                "step_id": "arch_big_picture",
                "card_text": "운영 아키텍처 큰 그림 보기",
                "user_query": "OpenShift 운영 아키텍처는 어떤 영역부터 순서대로 보면 돼?",
                "learning_objective": "외부, DMZ, 내부망, DB, 스토리지, 모니터링 영역을 한 번에 잡는다.",
                "answer_outline": [
                    "먼저 외부와 DMZ 경계에서 트래픽이 들어오는 흐름을 확인한다.",
                    "그 다음 내부망의 OpenShift 영역과 주요 플랫폼 컴포넌트를 본다.",
                    "DB, 스토리지, 모니터링 영역은 운영 영향도를 판단하는 보조 축으로 함께 본다.",
                ],
                "source_chunk_ids": [
                    "architecture--DSGN-005-001--default--none--design-summary--summary--3e8f3baf",
                ],
                "expected_terms": ["OpenShift Container Platform", "DMZ", "내부망", "Data Base", "HAProxy"],
                "image_roles": ["diagram", "main_diagram"],
                "allow_supporting_anchor": True,
            },
            {
                "step_id": "arch_storage_monitoring",
                "card_text": "스토리지와 모니터링 연결 보기",
                "user_query": "운영에서 스토리지와 모니터링은 어떤 순서로 확인하면 돼?",
                "learning_objective": "PVC, Prometheus, AlertManager가 어떤 운영 근거로 쓰이는지 확인한다.",
                "answer_outline": [
                    "서비스 저장 영역과 모니터링 저장 영역을 구분해서 본다.",
                    "PVC가 어떤 용도로 할당되는지 확인한다.",
                    "Prometheus와 AlertManager는 운영 상태 확인과 장애 대응의 근거로 연결한다.",
                ],
                "source_chunk_ids": [
                    "architecture--DSGN-005-030--default--none--design-summary--summary--7c8d4892"
                ],
                "expected_terms": ["PVC", "Prometheus", "AlertManager", "Logging"],
                "image_roles": ["diagram", "table"],
            },
        ],
    },
    {
        "guide_id": "service_flow_network_reading",
        "stage_id": "architecture",
        "title": "서비스 흐름과 네트워크 읽기",
        "learning_goal": "서비스 요청, 인증/인가, 라우팅, URL 매핑을 운영자가 추적할 수 있게 한다.",
        "next_guide_id": "cicd_change_approval_flow",
        "steps": [
            {
                "step_id": "service_request_flow",
                "card_text": "서비스 요청 흐름 따라가기",
                "user_query": "사용자 요청이 서비스까지 가는 흐름은 어디부터 보면 돼?",
                "learning_objective": "Gateway, HAProxy, Ingress Router, Envoy Proxy, Virtual Service, 서비스 Pod 흐름을 연결한다.",
                "answer_outline": [
                    "먼저 사용자 요청이 HAProxy와 Ingress Router로 들어오는 진입 경로를 본다.",
                    "그 다음 Envoy Proxy와 Virtual Service가 서비스 Pod로 연결하는 흐름을 확인한다.",
                    "인증/인가 요청과 처리 결과 반환은 진입 경로를 이해한 뒤 별도 응답 흐름으로 읽는다.",
                ],
                "source_chunk_ids": [
                    "architecture--DSGN-005-201--default--none--design-summary--summary--a4358c0d",
                    "architecture--DSGN-005-205--default--none--design-summary--summary--217a9505",
                ],
                "expected_terms": ["Gateway", "HAProxy", "Ingress Router", "Virtual Service", "POD", "Envoy Proxy"],
            },
            {
                "step_id": "service_url_mapping",
                "card_text": "URL 매핑과 서비스 연결 보기",
                "user_query": "URL 경로와 서비스 Pod 매핑은 어떻게 읽으면 돼?",
                "learning_objective": "외부/internal URL prefix가 gateway와 서비스 Pod로 어떻게 연결되는지 본다.",
                "answer_outline": [
                    "외부 URL과 internal URL prefix를 먼저 구분한다.",
                    "각 prefix가 gateway와 서비스 Pod 중 어디로 연결되는지 본다.",
                    "운영 확인 시에는 URL, gateway, service, pod 이름을 한 묶음으로 추적한다.",
                ],
                "source_chunk_ids": [
                    "architecture--DSGN-005-209--default--none--design-summary--summary--39f5045a",
                ],
                "expected_terms": ["Virtual Service", "Gateway", "Pod", "URL"],
                "allow_supporting_anchor": True,
            },
        ],
    },
    {
        "guide_id": "cicd_change_approval_flow",
        "stage_id": "architecture",
        "title": "CI/CD 변경과 운영 승인 흐름",
        "learning_goal": "소스 변경부터 운영 배포 승인, GitOps 반영까지의 실무 흐름을 이해한다.",
        "next_guide_id": "unit_test_verification_flow",
        "steps": [
            {
                "step_id": "cicd_overall_flow",
                "card_text": "운영 배포 승인 흐름 이해하기",
                "user_query": "운영 배포 승인 흐름은 어떤 순서로 이해하면 돼?",
                "learning_objective": "형상 변경, 빌드, 검증, 운영 승인 Gate, ArgoCD 반영을 연결한다.",
                "answer_outline": [
                    "개발 변경은 형상관리와 빌드 파이프라인에서 시작한다.",
                    "검증 환경 반영 후 운영 배포 승인 Gate를 통과해야 한다.",
                    "운영 반영은 ArgoCD와 배포 manifest 흐름으로 추적한다.",
                ],
                "source_chunk_ids": [
                    "architecture--DSGN-005-401--default--none--design-summary--summary--7a897e89",
                    "architecture--DSGN-005-402--default--none--design-summary--summary--2a966715",
                    "architecture--DSGN-005-403--default--none--design-summary--summary--23f6f4dd",
                ],
                "expected_terms": ["Tekton", "ArgoCD", "Quay", "운영배포 승인 Gate"],
            },
            {
                "step_id": "cicd_key_changes",
                "card_text": "CI/CD 주요 변경사항 보기",
                "user_query": "CI/CD 주요 변경사항은 어떤 순서로 보면 돼?",
                "learning_objective": "GitOps, manifest 관리, Tekton 파이프라인, Kustomize 렌더링을 확인한다.",
                "answer_outline": [
                    "애플리케이션 manifest가 Git을 통해 관리되는지 먼저 본다.",
                    "Tekton 파이프라인과 GitOps 반영 흐름을 함께 확인한다.",
                    "Kustomize 기반 렌더링은 환경별 배포 차이를 이해하는 기준으로 본다.",
                ],
                "source_chunk_ids": [
                    "architecture--DSGN-005-402--default--none--design-summary--summary--2a966715"
                ],
                "expected_terms": ["GitOps", "ArgoCD", "Tekton", "Kustomize", "GitLab"],
            },
            {
                "step_id": "cicd_staging_validation",
                "card_text": "검증 반영과 승인 확인하기",
                "user_query": "검증 환경 반영과 승인 과정은 어떤 순서로 보면 돼?",
                "learning_objective": "SR branch, MR, DEV/STG branch, 현업 테스트, 승인 흐름을 확인한다.",
                "answer_outline": [
                    "요청은 SR branch와 개발 작업에서 시작한다.",
                    "개발 반영 후 검증 반영 MR과 현업 테스트를 확인한다.",
                    "승인 이후 검증 서버 배포와 결과 흐름을 따라간다.",
                ],
                "source_chunk_ids": [
                    "architecture--DSGN-005-403--default--none--design-summary--summary--23f6f4dd"
                ],
                "expected_terms": ["SR branch", "MR", "DEV branch", "STG branch", "GitLab"],
            },
        ],
    },
    {
        "guide_id": "unit_test_verification_flow",
        "stage_id": "unit_test",
        "title": "운영 검증을 위한 단위 테스트 읽기",
        "learning_goal": "노드, 서비스 메시, HA, PVC 같은 운영 핵심 항목의 검증 방법과 기대 상태를 읽는다.",
        "next_guide_id": "integration_cicd_flow",
        "steps": [
            {
                "step_id": "unit_node_status",
                "card_text": "노드 상태 검증부터 보기",
                "user_query": "운영자가 기본 상태를 확인하려면 노드부터 어떻게 보면 돼?",
                "learning_objective": "노드 목록과 역할, CLI/Web Console 확인 기준을 잡는다.",
                "answer_outline": [
                    "먼저 전체 노드 목록과 역할 구성을 확인한다.",
                    "CLI와 Web Console에서 동일한 상태가 보이는지 비교한다.",
                    "master, infra, router, storage, worker 역할이 기대 구성과 맞는지 본다.",
                ],
                "source_chunk_ids": [
                    "unit-test--TEST-UN-OCP-01-01--plan--none--test-case-summary--summary--ca27205f"
                ],
                "expected_terms": ["oc get node", "CLI", "Web Console", "master", "worker"],
                "image_roles": ["expected_state_indicator", "command_result_evidence"],
            },
            {
                "step_id": "unit_service_mesh_status",
                "card_text": "Service Mesh 정상 상태 확인하기",
                "user_query": "Service Mesh가 정상인지 화면과 명령어에서 무엇을 보면 돼?",
                "learning_objective": "SMCP Ready, istiod, ingress endpoint 상태를 확인한다.",
                "answer_outline": [
                    "Service Mesh Control Plane Ready 상태를 먼저 확인한다.",
                    "istiod Pod와 ingress endpoint가 기대 상태인지 본다.",
                    "명령 결과와 콘솔 화면을 함께 증적으로 사용한다.",
                ],
                "source_chunk_ids": [
                    "unit-test--TEST-UN-OCP-08-07--plan--none--test-case-summary--summary--ce8971f4"
                ],
                "expected_terms": ["SMCP", "Ready", "istiod", "ingress endpoint"],
                "image_roles": ["expected_state_indicator", "command_result_evidence"],
            },
            {
                "step_id": "unit_pvc_mount",
                "card_text": "PVC 마운트 검증하기",
                "user_query": "PVC가 Pod에 제대로 붙었는지는 어떤 순서로 확인해?",
                "learning_objective": "PVC 생성, Deployment 마운트, 파일 생성 확인 흐름을 본다.",
                "answer_outline": [
                    "PVC와 Deployment 정의를 먼저 확인한다.",
                    "Pod에 PVC가 마운트되는지 본다.",
                    "파일 생성이나 접근 결과를 통해 실제 사용 가능 여부를 확인한다.",
                ],
                "source_chunk_ids": [
                    "unit-test--TEST-UN-OCP-25-01--plan--none--test-case-summary--summary--14c5fc79"
                ],
                "expected_terms": ["PVC", "Pod", "Deployment", "마운트"],
                "image_roles": ["expected_state_indicator", "command_result_evidence"],
            },
        ],
    },
    {
        "guide_id": "integration_cicd_flow",
        "stage_id": "integration_test",
        "title": "통합 테스트 CI/CD 흐름",
        "learning_goal": "파이프라인 시작부터 빌드, 배포, 서비스 접근 확인까지 실무 순서로 학습한다.",
        "next_guide_id": "performance_bottleneck_review",
        "steps": [
            {
                "step_id": "integration_pipeline_success",
                "card_text": "파이프라인 성공 흐름 확인하기",
                "user_query": "파이프라인이 성공했다는 건 화면에서 뭘 보면 돼?",
                "learning_objective": "Trigger, Clone, S2I/build, rollout, service access 성공 증적을 확인한다.",
                "answer_outline": [
                    "파이프라인 Trigger 이후 소스 Clone과 S2I/build가 이어지는지 본다.",
                    "Deployment rollout이 정상 완료되는지 확인한다.",
                    "서비스 접근 확인까지 이어져야 성공 흐름으로 본다.",
                ],
                "source_chunk_ids": [
                    "integrat-fce72e--1--default--none--integration-s-76fdd8--summary--d6e2c5ce"
                ],
                "expected_terms": ["Trigger", "Clone", "S2I", "Deployment", "서비스 접근"],
                "image_roles": ["success_state", "expected_state_indicator", "command_result_evidence"],
            },
            {
                "step_id": "integration_failure_troubleshooting",
                "card_text": "실패 상태와 로그 확인하기",
                "user_query": "파이프라인이나 배포가 실패하면 어떤 상태와 로그부터 봐야 해?",
                "learning_objective": "Failed 파이프라인, 빌드 오류 로그, CrashLoopBackOff Pod 상태를 순서대로 확인한다.",
                "answer_outline": [
                    "먼저 파이프라인 실행 상태가 Failed인지 확인한다.",
                    "Clone, S2I, build 단계의 콘솔 로그에서 컴파일 오류나 build failed 메시지를 찾는다.",
                    "배포 이후에는 Pod 상태가 CrashLoopBackOff인지 보고 로그와 배포 정보를 함께 확인한다.",
                ],
                "source_chunk_ids": [
                    "integrat-fce72e--3--default--none--integration-s-76fdd8--summary--46ae2d9a",
                    "integrat-fce72e--3--default--none--integration-s-c7171c--slide-006--cd703b45",
                    "integrat-fce72e--3--default--none--integration-s-c7171c--slide-042--447feee8",
                ],
                "expected_terms": ["Failed", "Build failed", "CrashLoopBackOff", "console", "Pod"],
                "image_roles": ["failure_state", "console_output", "expected_state_indicator"],
            }
        ],
    },
    {
        "guide_id": "performance_bottleneck_review",
        "stage_id": "perf_test",
        "title": "성능 테스트 병목 분석 흐름",
        "learning_goal": "성능 목표, 결과, 병목, 개선 포인트를 운영 관점에서 순서대로 확인한다.",
        "next_guide_id": "completion_report_reading_path",
        "steps": [
            {
                "step_id": "perf_goal_context",
                "card_text": "성능 목표와 조건 먼저 보기",
                "user_query": "성능 테스트는 어떤 목표와 조건부터 확인해야 해?",
                "learning_objective": "TPS 목표, 환경 차이, 테스트 반복 조건을 확인한다.",
                "answer_outline": [
                    "성능 목표와 테스트 환경을 먼저 확인한다.",
                    "운영환경과 Staging 환경의 자원 차이를 분리해서 본다.",
                    "이슈 발생 시 튜닝 후 재테스트가 반복될 수 있음을 전제로 결과를 해석한다.",
                ],
                "source_chunk_ids": [
                    "perf-test--3--default--none--perf-section-summary--summary--f90f298e",
                ],
                "expected_terms": ["TPS", "Staging", "테스트 환경", "튜닝", "재테스트"],
                "image_roles": ["table", "dashboard_metric"],
                "allow_supporting_anchor": True,
            },
            {
                "step_id": "perf_result_bottleneck",
                "card_text": "병목과 개선 포인트 확인하기",
                "user_query": "성능 테스트 결과에서 병목과 개선 포인트는 어디부터 보면 돼?",
                "learning_objective": "DB SQL 응답 지연, Connection Pool, worker-thread, HPA, HAProxy를 순서대로 확인한다.",
                "answer_outline": [
                    "먼저 전체 응답시간 지연이 발생한 구간을 확인한다.",
                    "DB SQL 응답 지연과 DB Connection Pool 대기 여부를 함께 본다.",
                    "worker-thread 수가 DB Connection Pool보다 과도하지 않은지 조정 포인트로 본다.",
                    "HPA scale-out과 HAProxy/Router 자원 지표를 보조 확인한다.",
                ],
                "source_chunk_ids": [
                    "perf-test--4--default--none--perf-section-summary--summary--10bd6950"
                ],
                "expected_terms": ["DB SQL 응답 지연", "DB Connection Pool", "worker-thread", "HPA", "HAProxy"],
                "image_roles": ["dashboard_metric", "command_result_evidence"],
            },
            {
                "step_id": "perf_improvement_actions",
                "card_text": "개선 권고 정리하기",
                "user_query": "성능 개선 권고는 어떤 항목부터 정리하면 돼?",
                "learning_objective": "DBMS 자원, DB Connection Pool, worker-thread, JVM heap, Pod 배치를 개선 후보로 정리한다.",
                "answer_outline": [
                    "DBMS SQL 응답시간과 DB Connection Pool 상향 조정 필요성을 먼저 본다.",
                    "worker-thread와 Connection Pool의 상대 크기를 조정 포인트로 본다.",
                    "Java Heap Size, Node 부하 분산, Pod 자원 설정을 함께 검토한다.",
                ],
                "source_chunk_ids": [
                    "perf-test--5--default--none--perf-section-summary--summary--9cc052ae"
                ],
                "expected_terms": ["DBMS", "DB Connection Pool", "worker-thread", "Java Heap", "Pod"],
                "image_roles": ["dashboard_metric", "table"],
            },
        ],
    },
    {
        "guide_id": "completion_report_reading_path",
        "stage_id": "completion",
        "title": "완료보고서 실무 읽기 순서",
        "learning_goal": "완료보고서를 사업 배경, 아키텍처 결과, 서비스 전환, 테스트 결과 순서로 읽는다.",
        "steps": [
            {
                "step_id": "completion_project_context",
                "card_text": "사업 범위와 추진 배경 보기",
                "user_query": "완료보고서는 사업 범위와 배경을 어디부터 보면 돼?",
                "learning_objective": "사업 기간, 범위, 이관/재구축 범위를 먼저 잡는다.",
                "answer_outline": [
                    "사업명, 기간, 범위를 먼저 확인한다.",
                    "컨테이너 이관과 재구축 범위를 구분한다.",
                    "기존 구성 제거와 신규 운영 구조를 다음 단계로 연결한다.",
                ],
                "source_chunk_ids": [
                    "completion--CH-02--default--none--chapter-summary--summary--54364cf6",
                    "completion--CH-03--default--none--chapter-summary--summary--52615f5f",
                ],
                "expected_terms": ["사업 기간", "사업 범위", "컨테이너 이관", "재구축"],
            },
            {
                "step_id": "completion_architecture_result",
                "card_text": "아키텍처 구성 결과 확인하기",
                "user_query": "완료보고서에서 아키텍처 구성 결과는 어떤 순서로 보면 돼?",
                "learning_objective": "목표 아키텍처, H/W, S/W, 네트워크, 구성 결과를 확인한다.",
                "answer_outline": [
                    "목표 아키텍처 구성도를 먼저 본다.",
                    "H/W와 S/W 제반 품목을 구성 결과와 연결한다.",
                    "네트워크와 플랫폼 구성 요소를 운영 관점으로 확인한다.",
                ],
                "source_chunk_ids": [
                    "completion--CH-03--default--none--chapter-summary--summary--52615f5f"
                ],
                "expected_terms": ["목표 아키텍처", "H/W", "S/W", "OpenShift Container Platform"],
                "image_roles": ["diagram", "dashboard_metric"],
            },
            {
                "step_id": "completion_test_result",
                "card_text": "테스트 결과와 마무리 확인하기",
                "user_query": "완료보고서에서 테스트 결과는 어떤 순서로 정리하면 돼?",
                "learning_objective": "단위, 통합, 성능 테스트 결과와 최종 개선 포인트를 함께 본다.",
                "answer_outline": [
                    "테스트 개요와 목적을 먼저 본다.",
                    "단위 테스트, 통합 테스트, 성능 테스트 결과를 구분해 정리한다.",
                    "성능 분석과 개선 포인트를 최종 운영 인수 관점으로 연결한다.",
                ],
                "source_chunk_ids": [
                    "completion--CH-05--default--none--chapter-summary--summary--fe825e06",
                    "completion--CH-05--default--none--chapter-slide-detail--slide-081--04bc329b",
                    "completion--CH-05--default--none--chapter-slide-detail--slide-082--1bb6d296",
                ],
                "expected_terms": ["단위 테스트", "통합", "성능 테스트", "응답시간", "DBMS"],
                "image_roles": ["table", "console_output", "command_result_evidence"],
            },
        ],
    },
]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _manifest_label(course_dir: Path) -> str:
    if course_dir.is_absolute():
        return str(course_dir / "manifests" / "course_v1.json")
    return (course_dir / "manifests" / "course_v1.json").as_posix()


def _load_chunks(course_dir: Path) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for path in sorted((course_dir / "chunks").glob("*.json")):
        payload = _read_json(path)
        if isinstance(payload, dict):
            chunks.append(payload)
    return chunks


def _load_manifest(course_dir: Path) -> dict[str, Any]:
    path = course_dir / "manifests" / "course_v1.json"
    return _read_json(path) if path.exists() else {}


def _tokens(value: Any) -> list[str]:
    text = str(value or "")
    return re.findall(r"[A-Za-z0-9가-힣][A-Za-z0-9가-힣_./:#-]*", text)


def _compact(value: Any, *, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[:limit].rstrip()


def _is_weak_title(title: str) -> bool:
    normalized = title.strip().lower()
    if not normalized:
        return True
    if normalized in SOURCE_ONLY_TITLES:
        return True
    if any(fragment in title for fragment in SOURCE_ONLY_TITLE_FRAGMENTS):
        return True
    if re.fullmatch(r"[\d./:# -]+", title):
        return True
    if re.fullmatch(r"(?:slide|page)\s*\d+", normalized):
        return True
    return False


def _is_source_only_candidate(
    chunk: dict[str, Any],
    *,
    body_tokens: int,
    search_tokens: int,
    image_context_anchor: bool = False,
) -> bool:
    if image_context_anchor:
        return False
    title = str(chunk.get("title") or "")
    native_id = str(chunk.get("native_id") or "")
    if _is_weak_title(title) and body_tokens < 25:
        return True
    if native_id.startswith("CH-01") and body_tokens == 0:
        return True
    if body_tokens == 0 and search_tokens < 18:
        return True
    return False


def _image_roles(attachments: list[Any]) -> list[str]:
    roles: list[str] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        for key in ("instructional_role", "role"):
            role = str(attachment.get(key) or "").strip()
            if role and role not in roles:
                roles.append(role)
        multi = attachment.get("instructional_roles")
        if isinstance(multi, list):
            for item in multi:
                role = str(item or "").strip()
                if role and role not in roles:
                    roles.append(role)
    return roles


def _chunk_evidence_text(chunk: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "title",
        "body_md",
        "search_text",
        "visual_text",
        "visual_summary",
        "ocr_text",
    ):
        value = chunk.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    for key in ("content", "visual", "structured", "facets"):
        value = chunk.get(key)
        if isinstance(value, (dict, list)):
            parts.append(json.dumps(value, ensure_ascii=False))
    attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        parts.append(json.dumps(attachment, ensure_ascii=False))
    return "\n".join(parts).lower()


def _trusted_official_docs(docs: list[Any]) -> list[dict[str, Any]]:
    trusted: list[dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        score = float(doc.get("score") or 0)
        if doc.get("trusted") is True or score >= 0.7:
            trusted.append(doc)
    return trusted


def classify_learning_anchor(chunk: dict[str, Any]) -> dict[str, Any]:
    body = str(chunk.get("body_md") or "")
    search_text = str(chunk.get("search_text") or "")
    title = str(chunk.get("title") or "")
    body_tokens = len(_tokens(body))
    search_tokens = len(_tokens(search_text))
    attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
    slide_refs = chunk.get("slide_refs") if isinstance(chunk.get("slide_refs"), list) else []
    related_docs = chunk.get("related_official_docs") if isinstance(chunk.get("related_official_docs"), list) else []
    trusted_docs = _trusted_official_docs(related_docs)
    roles = _image_roles(attachments)
    image_context_anchor = body_tokens == 0 and search_tokens >= 12 and len(attachments) >= 3 and bool(STATEFUL_IMAGE_ROLES & set(roles))
    tour_stop = chunk.get("tour_stop") if isinstance(chunk.get("tour_stop"), dict) else {}
    route_role = str(tour_stop.get("route_role") or "")
    review_status = str(chunk.get("review_status") or "")
    review_notes = [str(item) for item in chunk.get("review_notes", []) if str(item).strip()] if isinstance(chunk.get("review_notes"), list) else []
    quality_score = float(chunk.get("quality_score") or 0)

    score = 0
    reasons: list[str] = []
    issues: list[str] = []

    if body_tokens >= 80:
        score += 30
        reasons.append("substantial_body")
    elif body_tokens >= 25:
        score += 18
        reasons.append("usable_body")
    elif body_tokens > 0:
        score += 6
        issues.append("thin_body")
    else:
        issues.append("empty_body")

    if search_tokens >= 80:
        score += 16
        reasons.append("rich_search_text")
    elif search_tokens >= 30:
        score += 10
        reasons.append("usable_search_text")
    else:
        issues.append("thin_search_text")

    if attachments:
        score += min(14, 4 + len(attachments) // 4)
        reasons.append("has_images")
    if roles:
        score += 8
        reasons.append("has_image_roles")
    if STATEFUL_IMAGE_ROLES & set(roles):
        score += 8
        reasons.append("has_operational_image_evidence")
    if image_context_anchor:
        score += 12
        reasons.append("image_context_evidence_anchor")

    if trusted_docs:
        score += 10
        reasons.append("trusted_official_mapping")
    elif related_docs:
        score += 3
        issues.append("official_mapping_needs_review")

    if route_role == "start_here":
        score += 8
        reasons.append("stage_route_start")
    elif route_role == "then_open":
        score += 5
        reasons.append("stage_route_followup")

    if review_status == "approved":
        score += 8
    elif review_status:
        issues.append(f"review_status:{review_status}")

    if quality_score >= 0.9:
        score += 6
    elif quality_score and quality_score < 0.75:
        issues.append("low_quality_score")

    if _is_weak_title(title):
        score -= 8
        issues.append("weak_or_source_only_title")

    if _is_source_only_candidate(chunk, body_tokens=body_tokens, search_tokens=search_tokens, image_context_anchor=image_context_anchor):
        score -= 18
        issues.append("source_only_or_cover_like")

    if "thin_content" in review_notes:
        score -= 10
        issues.append("review_note:thin_content")

    score = max(0, min(100, score))
    if "source_only_or_cover_like" in issues:
        classification = "source_only"
    elif score >= 70 and body_tokens >= 25 and "empty_body" not in issues:
        classification = "primary_learning_anchor"
    elif score >= 45 and (body_tokens > 0 or image_context_anchor):
        classification = "supporting_evidence"
    elif issues:
        classification = "needs_review"
    else:
        classification = "source_only"

    beginner_candidate = classification == "primary_learning_anchor"
    if classification == "supporting_evidence" and route_role in {"start_here", "then_open"} and body_tokens >= 25:
        beginner_candidate = True

    return {
        "classification": classification,
        "learning_score": score,
        "beginner_candidate": beginner_candidate,
        "reasons": reasons,
        "issues": sorted(set(issues)),
        "metrics": {
            "body_tokens": body_tokens,
            "search_tokens": search_tokens,
            "slide_count": len(slide_refs),
            "image_count": len(attachments),
            "image_roles": roles,
            "official_doc_count": len(related_docs),
            "trusted_official_doc_count": len(trusted_docs),
            "quality_score": quality_score,
        },
    }


def _anchor_row(chunk: dict[str, Any]) -> dict[str, Any]:
    audit = classify_learning_anchor(chunk)
    tour_stop = chunk.get("tour_stop") if isinstance(chunk.get("tour_stop"), dict) else {}
    facets = chunk.get("facets") if isinstance(chunk.get("facets"), dict) else {}
    return {
        "chunk_id": str(chunk.get("chunk_id") or ""),
        "stage_id": str(chunk.get("stage_id") or ""),
        "native_id": str(chunk.get("native_id") or ""),
        "title": str(chunk.get("title") or ""),
        "chunk_kind": str(chunk.get("chunk_kind") or ""),
        "classification": audit["classification"],
        "learning_score": audit["learning_score"],
        "beginner_candidate": audit["beginner_candidate"],
        "route_role": str(tour_stop.get("route_role") or ""),
        "stop_order": int(tour_stop.get("stop_order") or 0),
        "next_chunk_id": str(tour_stop.get("next_chunk_id") or ""),
        "summary": _compact(chunk.get("body_md") or chunk.get("search_text")),
        "technologies": list(facets.get("technologies") or [])[:10] if isinstance(facets.get("technologies"), list) else [],
        "network_zones": list(facets.get("network_zones") or [])[:10] if isinstance(facets.get("network_zones"), list) else [],
        "source_refs": {
            "slide_count": audit["metrics"]["slide_count"],
            "image_count": audit["metrics"]["image_count"],
            "official_doc_count": audit["metrics"]["official_doc_count"],
        },
        "evidence_roles": audit["metrics"]["image_roles"],
        "reasons": audit["reasons"],
        "issues": audit["issues"],
        "metrics": audit["metrics"],
    }


def build_anchor_audit(course_dir: Path, *, root_dir: Path | None = None) -> dict[str, Any]:
    root_dir = root_dir or Path(".")
    source_manifest = _manifest_label(course_dir)
    course_dir = (root_dir / course_dir).resolve() if not course_dir.is_absolute() else course_dir.resolve()
    manifest = _load_manifest(course_dir)
    chunks = _load_chunks(course_dir)
    rows = [_anchor_row(chunk) for chunk in chunks]
    rows.sort(key=lambda row: (row["stage_id"], row["stop_order"] or 9999, -int(row["learning_score"]), row["chunk_id"]))

    stage_summaries: dict[str, dict[str, Any]] = {}
    stage_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        stage_rows[str(row.get("stage_id") or "")].append(row)

    for stage_id, stage_items in sorted(stage_rows.items()):
        classifications = Counter(str(item.get("classification") or "") for item in stage_items)
        route_roles = Counter(str(item.get("route_role") or "none") or "none" for item in stage_items)
        candidates = [item for item in stage_items if item.get("beginner_candidate")]
        needs_review = [item for item in stage_items if item.get("classification") == "needs_review"]
        stage_summaries[stage_id] = {
            "chunk_count": len(stage_items),
            "classification_counts": dict(sorted(classifications.items())),
            "route_role_counts": dict(sorted(route_roles.items())),
            "beginner_candidate_count": len(candidates),
            "needs_review_count": len(needs_review),
            "top_beginner_candidates": [
                {
                    "chunk_id": item["chunk_id"],
                    "title": item["title"],
                    "learning_score": item["learning_score"],
                    "route_role": item["route_role"],
                    "issues": item["issues"],
                }
                for item in sorted(candidates, key=lambda item: (-int(item["learning_score"]), item["stop_order"] or 9999))[:8]
            ],
            "weak_route_starts": [
                {
                    "chunk_id": item["chunk_id"],
                    "title": item["title"],
                    "classification": item["classification"],
                    "issues": item["issues"],
                }
                for item in stage_items
                if item.get("route_role") in {"start_here", "then_open"} and item.get("classification") in {"source_only", "needs_review"}
            ][:10],
        }

    overall = Counter(str(row.get("classification") or "") for row in rows)
    id_like_title_count = sum(1 for row in rows if re.search(r"\b(?:DSGN|TEST|CH|KMSC|OCP|PERF|ITG)[-A-Z0-9]*", str(row.get("title") or ""), re.I))
    return {
        "canonical_model": AUDIT_SCHEMA,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_manifest": source_manifest,
        "source_chunk_count": len(chunks),
        "source_route_stop_count": int((manifest.get("tour") or {}).get("stop_count") or 0) if isinstance(manifest.get("tour"), dict) else 0,
        "summary": {
            "classification_counts": dict(sorted(overall.items())),
            "beginner_candidate_count": sum(1 for row in rows if row.get("beginner_candidate")),
            "needs_review_count": sum(1 for row in rows if row.get("classification") == "needs_review"),
            "source_only_count": sum(1 for row in rows if row.get("classification") == "source_only"),
            "id_like_title_count": id_like_title_count,
        },
        "stage_summaries": stage_summaries,
        "anchors": rows,
    }


def write_anchor_audit(course_dir: Path, output_path: Path, *, root_dir: Path | None = None) -> dict[str, Any]:
    root_dir = root_dir or Path(".")
    resolved_output = (root_dir / output_path).resolve() if not output_path.is_absolute() else output_path.resolve()
    payload = build_anchor_audit(course_dir, root_dir=root_dir)
    _write_json(resolved_output, payload)
    return payload


def _chunk_maps(course_dir: Path, *, root_dir: Path | None = None) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    root_dir = root_dir or Path(".")
    resolved_course_dir = (root_dir / course_dir).resolve() if not course_dir.is_absolute() else course_dir.resolve()
    chunks = _load_chunks(resolved_course_dir)
    audit = build_anchor_audit(course_dir, root_dir=root_dir)
    return (
        {str(chunk.get("chunk_id") or ""): chunk for chunk in chunks},
        {str(row.get("chunk_id") or ""): row for row in audit["anchors"]},
    )


def _source_anchor_from_chunk(chunk: dict[str, Any], audit_row: dict[str, Any] | None, *, index: int) -> dict[str, Any]:
    return {
        "chunk_id": str(chunk.get("chunk_id") or ""),
        "native_id": str(chunk.get("native_id") or ""),
        "hidden_from_user": True,
        "anchor_role": "primary" if index == 0 else "supporting",
        "stage_id": str(chunk.get("stage_id") or ""),
        "title": str(chunk.get("title") or ""),
        "learning_classification": str((audit_row or {}).get("classification") or "missing"),
        "learning_score": int((audit_row or {}).get("learning_score") or 0),
    }


def _step_quality(source_rows: list[dict[str, Any] | None], definition: dict[str, Any]) -> dict[str, Any]:
    needs_review: list[str] = []
    if INTERNAL_ID_RE.search(str(definition.get("card_text") or "")):
        needs_review.append("card_text_internal_id_leak")
    if INTERNAL_ID_RE.search(str(definition.get("user_query") or "")):
        needs_review.append("query_internal_id_leak")
    if not source_rows:
        needs_review.append("missing_source_anchor")
    existing_rows = [row for row in source_rows if row is not None]
    supporting_anchor_ok = bool(definition.get("allow_supporting_anchor")) or len(existing_rows) >= 2
    for row in source_rows:
        if row is None:
            needs_review.append("missing_source_anchor")
            continue
        classification = str(row.get("classification") or "")
        if classification in {"source_only", "needs_review"}:
            needs_review.append(f"source_anchor_{classification}")
        elif classification == "supporting_evidence" and not supporting_anchor_ok:
            needs_review.append("source_anchor_not_primary")
    return {
        "status": "needs_review" if needs_review else "draft",
        "needs_review": sorted(set(needs_review)),
    }


def build_initial_guides(course_dir: Path, *, root_dir: Path | None = None) -> dict[str, Any]:
    root_dir = root_dir or Path(".")
    chunks_by_id, audit_by_id = _chunk_maps(course_dir, root_dir=root_dir)
    guides: list[dict[str, Any]] = []
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    guide_defs_by_id = {
        str(guide_def.get("guide_id") or ""): guide_def
        for guide_def in INITIAL_GUIDE_DEFINITIONS
        if str(guide_def.get("guide_id") or "").strip()
    }

    for guide_def in INITIAL_GUIDE_DEFINITIONS:
        steps: list[dict[str, Any]] = []
        raw_steps = guide_def.get("steps") if isinstance(guide_def.get("steps"), list) else []
        next_guide_id = str(guide_def.get("next_guide_id") or "")
        next_guide_def = guide_defs_by_id.get(next_guide_id) if next_guide_id else None
        next_guide_steps = next_guide_def.get("steps") if isinstance(next_guide_def, dict) and isinstance(next_guide_def.get("steps"), list) else []
        next_guide_entry = next_guide_steps[0] if next_guide_steps and isinstance(next_guide_steps[0], dict) else None
        for index, step_def in enumerate(raw_steps):
            source_chunk_ids = [str(item) for item in step_def.get("source_chunk_ids", []) if str(item).strip()]
            source_rows = [audit_by_id.get(chunk_id) for chunk_id in source_chunk_ids]
            anchors = [
                _source_anchor_from_chunk(chunks_by_id[chunk_id], audit_by_id.get(chunk_id), index=anchor_index)
                for anchor_index, chunk_id in enumerate(source_chunk_ids)
                if chunk_id in chunks_by_id
            ]
            has_local_next = index < len(raw_steps) - 1
            has_cross_guide_next = bool(not has_local_next and next_guide_id and next_guide_entry)
            step = {
                "step_id": str(step_def.get("step_id") or ""),
                "guide_id": str(guide_def.get("guide_id") or ""),
                "stage_id": str(guide_def.get("stage_id") or ""),
                "card_text": str(step_def.get("card_text") or ""),
                "user_query": str(step_def.get("user_query") or ""),
                "learning_objective": str(step_def.get("learning_objective") or ""),
                "answer_outline": list(step_def.get("answer_outline") or []),
                "source_anchors": anchors,
                "official_refs": list(step_def.get("official_refs") or []),
                "evidence_requirements": {
                    "requires_citation": True,
                    "requires_next_step": has_local_next or has_cross_guide_next,
                    "image_roles": list(step_def.get("image_roles") or []),
                },
                "expected_terms": list(step_def.get("expected_terms") or []),
                "next_step_ids": [str(raw_steps[index + 1].get("step_id"))] if has_local_next else [],
                "next_guide": {
                    "guide_id": next_guide_id,
                    "step_id": str(next_guide_entry.get("step_id") or ""),
                    "card_text": str(next_guide_entry.get("card_text") or ""),
                    "user_query": str(next_guide_entry.get("user_query") or ""),
                } if has_cross_guide_next and next_guide_entry else None,
                "quality": _step_quality(source_rows, step_def),
            }
            steps.append(step)
        guide_needs_review = sorted(
            {
                reason
                for step in steps
                for reason in (step.get("quality") or {}).get("needs_review", [])
                if str(reason).strip()
            }
        )
        guides.append(
            {
                "guide_id": str(guide_def.get("guide_id") or ""),
                "stage_id": str(guide_def.get("stage_id") or ""),
                "title": str(guide_def.get("title") or ""),
                "audience": "beginner_operator",
                "learning_goal": str(guide_def.get("learning_goal") or ""),
                "next_guide_id": next_guide_id,
                "next_guide_entry_step_id": str(next_guide_entry.get("step_id") or "") if next_guide_entry else "",
                "entry_step_id": str(steps[0].get("step_id") if steps else ""),
                "step_ids": [str(step.get("step_id") or "") for step in steps],
                "steps": steps,
                "quality": {
                    "status": "needs_review" if guide_needs_review else "draft",
                    "needs_review": guide_needs_review,
                },
            }
        )

    return {
        "canonical_model": GUIDE_SCHEMA,
        "generated_at": generated_at,
        "source_manifest": _manifest_label(course_dir),
        "guide_count": len(guides),
        "step_count": sum(len(guide.get("steps") or []) for guide in guides),
        "guides": guides,
    }


def write_initial_guides(course_dir: Path, output_path: Path, *, root_dir: Path | None = None) -> dict[str, Any]:
    root_dir = root_dir or Path(".")
    resolved_output = (root_dir / output_path).resolve() if not output_path.is_absolute() else output_path.resolve()
    payload = build_initial_guides(course_dir, root_dir=root_dir)
    _write_json(resolved_output, payload)
    return payload


def _public_learning_text(value: Any, *, limit: int = 500) -> str:
    text = INTERNAL_ID_RE.sub("", str(value or ""))
    text = re.sub(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b", "", text)
    text = re.sub(r"\s+", " ", text).strip(" -:_")
    if limit and len(text) > limit:
        text = text[:limit].rstrip()
    return text


def _unique_strings(values: Iterable[Any], *, limit: int = 0) -> list[str]:
    rows: list[str] = []
    for value in values:
        text = _public_learning_text(value, limit=limit or 500)
        if text and text not in rows:
            rows.append(text)
    return rows


def _source_chunks_for_step(step: dict[str, Any], chunks_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for chunk_id in _guide_step_source_chunk_ids(step):
        chunk = chunks_by_id.get(chunk_id)
        if isinstance(chunk, dict):
            chunks.append(chunk)
    return chunks


def _guide_step_source_chunk_ids(step: dict[str, Any]) -> list[str]:
    anchors = step.get("source_anchors") if isinstance(step.get("source_anchors"), list) else []
    chunk_ids: list[str] = []
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        chunk_id = str(anchor.get("chunk_id") or "").strip()
        if chunk_id and chunk_id not in chunk_ids:
            chunk_ids.append(chunk_id)
    return chunk_ids


def _source_terms(step: dict[str, Any], source_chunks: list[dict[str, Any]]) -> list[str]:
    terms = _unique_strings(step.get("expected_terms") if isinstance(step.get("expected_terms"), list) else [], limit=80)
    for chunk in source_chunks:
        facets = chunk.get("facets") if isinstance(chunk.get("facets"), dict) else {}
        for key in ("technologies", "network_zones", "service_names", "components"):
            value = facets.get(key)
            if isinstance(value, list):
                terms.extend(_unique_strings(value, limit=80))
    return list(dict.fromkeys(term for term in terms if term))


def _source_titles(source_chunks: list[dict[str, Any]]) -> list[str]:
    return _unique_strings((chunk.get("title") for chunk in source_chunks), limit=140)


def _source_summary(source_chunks: list[dict[str, Any]], *, limit: int = 700) -> str:
    rows: list[str] = []
    for chunk in source_chunks:
        for key in ("search_text", "body_md", "visual_text"):
            text = _public_learning_text(chunk.get(key), limit=OPS_SOURCE_SUMMARY_TEXT_LIMIT)
            if text:
                rows.append(text)
                break
    return _public_learning_text(" ".join(dict.fromkeys(rows)), limit=limit)


def _source_image_texts(source_chunks: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for chunk in source_chunks:
        attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            rows.extend(
                _unique_strings(
                    [
                        attachment.get("visual_summary"),
                        attachment.get("caption_text"),
                        attachment.get("ocr_text"),
                        attachment.get("state_signal"),
                    ],
                    limit=240,
                )
            )
    return list(dict.fromkeys(row for row in rows if row))[:12]


def _source_image_roles(step: dict[str, Any], source_chunks: list[dict[str, Any]]) -> list[str]:
    requirements = step.get("evidence_requirements") if isinstance(step.get("evidence_requirements"), dict) else {}
    roles = _unique_strings(requirements.get("image_roles") if isinstance(requirements.get("image_roles"), list) else [], limit=80)
    for chunk in source_chunks:
        attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
        roles.extend(_image_roles(attachments))
    return list(dict.fromkeys(role for role in roles if role))


def _state_terms(source_chunks: list[dict[str, Any]], *, failure: bool) -> list[str]:
    failure_states = {"Failed", "Error", "CrashLoopBackOff", "Degraded", "OutOfSync", "Build failed"}
    normal_states = {"Running", "Ready", "Succeeded", "Available", "Progressing", "Synced"}
    wanted = failure_states if failure else normal_states
    states: list[str] = []
    for chunk in source_chunks:
        evidence = _chunk_evidence_text(chunk)
        for state in wanted:
            if state.lower() in evidence and state not in states:
                states.append(state)
        attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            state = str(attachment.get("state_signal") or "").strip()
            if state in wanted and state not in states:
                states.append(state)
    return states


def _evidence_sentences(source_chunks: list[dict[str, Any]], terms: list[str], *, limit: int = 4) -> list[str]:
    rows: list[str] = []
    needles = [term.lower() for term in terms if len(term) >= 2]
    for chunk in source_chunks:
        text = " ".join(
            str(chunk.get(key) or "")
            for key in ("body_md", "search_text", "visual_text")
            if str(chunk.get(key) or "").strip()
        )
        for sentence in re.split(r"(?<=[.!?。])\s+|\n+", text):
            clean = _public_learning_text(sentence, limit=OPS_SEQUENCE_TEXT_LIMIT)
            if not clean or clean in rows:
                continue
            lower = clean.lower()
            if not needles or any(term in lower for term in needles):
                rows.append(clean)
            if len(rows) >= limit:
                return rows
    return rows


def _query_variants_for_step(guide: dict[str, Any], step: dict[str, Any], terms: list[str]) -> list[str]:
    title = _public_learning_text(step.get("card_text") or step.get("learning_objective") or guide.get("title"), limit=80)
    goal = _public_learning_text(step.get("learning_objective") or guide.get("learning_goal"), limit=120)
    seed = _public_learning_text(step.get("user_query"), limit=120)
    variants = [seed] if seed else []
    if title:
        variants.append(f"{title}는 어떤 순서로 보면 돼?")
        variants.append(f"{title}에서 운영자가 먼저 확인할 것은 뭐야?")
    primary_terms = [term for term in terms if not INTERNAL_ID_RE.search(term)][:3]
    if primary_terms:
        variants.append(f"{', '.join(primary_terms)}는 운영 흐름에서 어떻게 연결돼?")
        variants.append(f"{primary_terms[0]} 상태를 확인할 때 무엇을 봐야 해?")
    if goal:
        variants.append(f"{goal} 관점에서 다음에 볼 단계는 뭐야?")
    return _unique_strings((variant for variant in variants if not INTERNAL_ID_RE.search(str(variant or ""))), limit=140)[:5]


def _official_ref_ids(source_chunks: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for chunk in source_chunks:
        docs = _trusted_official_docs(chunk.get("related_official_docs") if isinstance(chunk.get("related_official_docs"), list) else [])
        for doc in docs:
            ref = str(doc.get("section_id") or doc.get("book_slug") or doc.get("title") or "").strip()
            if ref and ref not in refs:
                refs.append(ref)
    return refs


def _official_mapping_summary(source_chunks: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for chunk in source_chunks:
        docs = _trusted_official_docs(chunk.get("related_official_docs") if isinstance(chunk.get("related_official_docs"), list) else [])
        for doc in docs[:2]:
            rows.append(_public_learning_text(doc.get("title") or doc.get("section_title") or doc.get("match_reason"), limit=120))
    return _public_learning_text(" ".join(dict.fromkeys(row for row in rows if row)), limit=360)


def _learning_embedding_text(chunk: dict[str, Any]) -> str:
    rows: list[str] = []
    for key in ("title", "learning_goal", "beginner_explanation", "source_summary", "official_mapping_summary"):
        value = str(chunk.get(key) or "").strip()
        if value:
            rows.append(value)
    for key in (
        "operational_sequence",
        "what_to_look_for",
        "normal_state",
        "failure_state",
        "query_variants",
        "visual_evidence_roles",
        "source_titles",
        "source_terms",
        "image_evidence_texts",
    ):
        value = chunk.get(key)
        if isinstance(value, list):
            rows.extend(str(item).strip() for item in value if str(item).strip())
    return "\n".join(dict.fromkeys(rows))


def build_ops_learning_chunks(
    course_dir: Path,
    guides_payload: dict[str, Any] | None = None,
    *,
    root_dir: Path | None = None,
) -> list[dict[str, Any]]:
    root_dir = root_dir or Path(".")
    resolved_course_dir = (root_dir / course_dir).resolve() if not course_dir.is_absolute() else course_dir.resolve()
    if guides_payload is None:
        guides_path = resolved_course_dir / "manifests" / "ops_learning_guides_v1.json"
        guides_payload = _read_json(guides_path) if guides_path.exists() else build_initial_guides(course_dir, root_dir=root_dir)
    chunks_by_id = {str(chunk.get("chunk_id") or ""): chunk for chunk in _load_chunks(resolved_course_dir)}
    guides = guides_payload.get("guides") if isinstance(guides_payload.get("guides"), list) else []
    learning_chunks: list[dict[str, Any]] = []
    for guide in guides:
        if not isinstance(guide, dict):
            continue
        steps = guide.get("steps") if isinstance(guide.get("steps"), list) else []
        for step in steps:
            if not isinstance(step, dict):
                continue
            source_chunks = _source_chunks_for_step(step, chunks_by_id)
            source_chunk_ids = [str(chunk.get("chunk_id") or "") for chunk in source_chunks if str(chunk.get("chunk_id") or "")]
            terms = _source_terms(step, source_chunks)
            sequence = _evidence_sentences(source_chunks, terms, limit=4)
            if not sequence:
                sequence = _unique_strings(
                    [
                        step.get("learning_objective"),
                        *(_source_titles(source_chunks)[:2]),
                    ],
                    limit=OPS_SEQUENCE_TEXT_LIMIT,
                )
            look_for = _unique_strings([*terms[:8], *_source_image_roles(step, source_chunks)[:4]], limit=120)
            title = _public_learning_text(step.get("card_text") or step.get("user_query") or step.get("step_id"), limit=120)
            learning_goal = _public_learning_text(step.get("learning_objective") or guide.get("learning_goal"), limit=260)
            source_summary = _source_summary(source_chunks)
            learning_chunk = {
                "canonical_model": LEARNING_CHUNK_SCHEMA,
                "chunk_type": "ops_learning_step",
                "learning_chunk_id": f"{guide.get('guide_id')}::{step.get('step_id')}",
                "guide_id": str(guide.get("guide_id") or ""),
                "step_id": str(step.get("step_id") or ""),
                "stage_id": str(step.get("stage_id") or guide.get("stage_id") or ""),
                "audience": str(guide.get("audience") or "beginner_operator"),
                "title": title,
                "learning_goal": learning_goal,
                "beginner_explanation": _public_learning_text(" ".join(part for part in [learning_goal, source_summary] if part), limit=700),
                "operational_sequence": sequence,
                "what_to_look_for": look_for,
                "normal_state": _state_terms(source_chunks, failure=False),
                "failure_state": _state_terms(source_chunks, failure=True),
                "visual_evidence_roles": _source_image_roles(step, source_chunks),
                "source_chunk_ids": source_chunk_ids,
                "source_titles": _source_titles(source_chunks),
                "source_terms": terms,
                "source_summary": source_summary,
                "hidden_native_ids": [
                    str(anchor.get("native_id") or "")
                    for anchor in (step.get("source_anchors") if isinstance(step.get("source_anchors"), list) else [])
                    if isinstance(anchor, dict) and str(anchor.get("native_id") or "").strip()
                ],
                "official_ref_ids": _official_ref_ids(source_chunks),
                "official_mapping_summary": _official_mapping_summary(source_chunks),
                "next_step_ids": list(step.get("next_step_ids") or []) if isinstance(step.get("next_step_ids"), list) else [],
                "next_guide": step.get("next_guide") if isinstance(step.get("next_guide"), dict) else None,
                "query_variants": _query_variants_for_step(guide, step, terms),
                "image_evidence_texts": _source_image_texts(source_chunks),
                "quality": step.get("quality") if isinstance(step.get("quality"), dict) else {"status": "draft", "needs_review": []},
            }
            learning_chunk["embedding_text"] = _learning_embedding_text(learning_chunk)
            learning_chunks.append(learning_chunk)
    return learning_chunks


def write_ops_learning_chunks(chunks: list[dict[str, Any]], output_path: Path, *, root_dir: Path | None = None) -> None:
    root_dir = root_dir or Path(".")
    resolved_output = (root_dir / output_path).resolve() if not output_path.is_absolute() else output_path.resolve()
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text("\n".join(json.dumps(chunk, ensure_ascii=False) for chunk in chunks) + "\n", encoding="utf-8")


def build_ops_learning_golden_cases(guides_payload: dict[str, Any]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for guide in guides_payload.get("guides", []):
        if not isinstance(guide, dict):
            continue
        for step in guide.get("steps", []):
            if not isinstance(step, dict):
                continue
            query = str(step.get("user_query") or "")
            anchors = step.get("source_anchors") if isinstance(step.get("source_anchors"), list) else []
            case = {
                "id": f"guide-{guide.get('guide_id')}-{step.get('step_id')}",
                "canonical_model": GOLDEN_CASE_SCHEMA,
                "category": _golden_category_for_step(step),
                "guide_id": str(guide.get("guide_id") or ""),
                "step_id": str(step.get("step_id") or ""),
                "query": query,
                "expected": {
                    "stage_id": str(step.get("stage_id") or guide.get("stage_id") or ""),
                    "chunk_ids": [str(anchor.get("chunk_id") or "") for anchor in anchors if isinstance(anchor, dict)],
                    "terms": list(step.get("expected_terms") or []),
                    "image_roles": list((step.get("evidence_requirements") or {}).get("image_roles") or []),
                    "must_include_citation": True,
                    "must_include_next_step": bool((step.get("evidence_requirements") or {}).get("requires_next_step")),
                    "must_not_expose_internal_ids": True,
                },
                "source": {
                    "native_ids": [str(anchor.get("native_id") or "") for anchor in anchors if isinstance(anchor, dict)],
                    "hidden_doc_anchor": True,
                },
                "quality": step.get("quality") or {"status": "draft", "needs_review": []},
            }
            cases.append(case)
    return cases


def _golden_category_for_step(step: dict[str, Any]) -> str:
    query = str(step.get("user_query") or "")
    if any(term in query for term in ("병목", "성능", "개선")):
        return "beginner_performance"
    if any(term in query for term in ("정상", "성공", "화면", "확인")):
        return "beginner_verification"
    if any(term in query for term in ("실패", "로그", "롤백")):
        return "beginner_troubleshooting"
    if "순서" in query or "흐름" in query:
        return "beginner_guided_step"
    return "beginner_operational_flow"


def validate_ops_learning_golden_cases(
    cases: list[dict[str, Any]],
    *,
    chunks_by_id: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for case in cases:
        reasons: list[str] = []
        case_id = str(case.get("id") or "")
        query = str(case.get("query") or "")
        expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
        if not case_id:
            reasons.append("missing_id")
        if case_id in seen_ids:
            reasons.append("duplicate_id")
        if INTERNAL_ID_RE.search(query):
            reasons.append("query_internal_id_leak")
        if not expected.get("chunk_ids"):
            reasons.append("missing_expected_chunk_ids")
        if not expected.get("terms"):
            reasons.append("missing_expected_terms")
        if chunks_by_id is not None:
            expected_chunk_ids = [str(item) for item in expected.get("chunk_ids", []) if str(item).strip()]
            expected_chunks = [chunks_by_id[chunk_id] for chunk_id in expected_chunk_ids if chunk_id in chunks_by_id]
            for chunk_id in expected_chunk_ids:
                if chunk_id not in chunks_by_id:
                    reasons.append(f"unknown_expected_chunk:{chunk_id}")
            source_text = "\n".join(_chunk_evidence_text(chunk) for chunk in expected_chunks)
            for term in [str(item) for item in expected.get("terms", []) if str(item).strip()]:
                if term.lower() not in source_text:
                    reasons.append(f"expected_term_not_in_source_chunk:{term}")
            source_roles: set[str] = set()
            for chunk in expected_chunks:
                attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
                source_roles.update(_image_roles(attachments))
            for role in [str(item) for item in expected.get("image_roles", []) if str(item).strip()]:
                if role not in source_roles:
                    reasons.append(f"expected_image_role_not_in_source_chunk:{role}")
        if reasons:
            rejected.append({**case, "quality_reasons": reasons})
        else:
            seen_ids.add(case_id)
            accepted.append(case)
    return accepted, rejected


def write_ops_learning_golden_cases(cases: list[dict[str, Any]], output_path: Path, *, root_dir: Path | None = None) -> None:
    root_dir = root_dir or Path(".")
    resolved_output = (root_dir / output_path).resolve() if not output_path.is_absolute() else output_path.resolve()
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text("\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n", encoding="utf-8")


def write_initial_guides_and_golden(
    course_dir: Path,
    guides_path: Path,
    golden_path: Path,
    *,
    learning_chunks_path: Path | None = None,
    root_dir: Path | None = None,
) -> dict[str, Any]:
    root_dir = root_dir or Path(".")
    guides_payload = write_initial_guides(course_dir, guides_path, root_dir=root_dir)
    cases = build_ops_learning_golden_cases(guides_payload)
    chunks_by_id, _ = _chunk_maps(course_dir, root_dir=root_dir)
    accepted, rejected = validate_ops_learning_golden_cases(cases, chunks_by_id=chunks_by_id)
    write_ops_learning_golden_cases(accepted, golden_path, root_dir=root_dir)
    learning_chunks = build_ops_learning_chunks(course_dir, guides_payload, root_dir=root_dir)
    if learning_chunks_path is not None:
        write_ops_learning_chunks(learning_chunks, learning_chunks_path, root_dir=root_dir)
    report = {
        "canonical_model": "ops_learning_golden_generation_report_v1",
        "guide_count": guides_payload["guide_count"],
        "step_count": guides_payload["step_count"],
        "generated_case_count": len(cases),
        "accepted_case_count": len(accepted),
        "rejected_case_count": len(rejected),
        "learning_chunk_count": len(learning_chunks),
        "rejected": rejected,
        "query_internal_id_leak_count": sum(1 for case in accepted if INTERNAL_ID_RE.search(str(case.get("query") or ""))),
    }
    return {"guides": guides_payload, "golden_cases": accepted, "learning_chunks": learning_chunks, "report": report}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Study-docs operational learning anchor audit.")
    parser.add_argument("--root-dir", type=Path, default=Path("."))
    parser.add_argument("--course-dir", type=Path, default=DEFAULT_COURSE_DIR)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_AUDIT_PATH)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root_dir = args.root_dir.resolve()
    payload = write_anchor_audit(args.course_dir, args.output_path, root_dir=root_dir)
    print(
        json.dumps(
            {
                "output_path": str((root_dir / args.output_path).resolve() if not args.output_path.is_absolute() else args.output_path.resolve()),
                "source_chunk_count": payload["source_chunk_count"],
                "source_route_stop_count": payload["source_route_stop_count"],
                "summary": payload["summary"],
                "stage_summaries": {
                    stage_id: {
                        "chunk_count": summary["chunk_count"],
                        "classification_counts": summary["classification_counts"],
                        "beginner_candidate_count": summary["beginner_candidate_count"],
                        "weak_route_starts": summary["weak_route_starts"],
                    }
                    for stage_id, summary in payload["stage_summaries"].items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
