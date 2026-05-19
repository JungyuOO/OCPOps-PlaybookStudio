# 질문을 smalltalk / meta / clarification / grounded answer로 분기하는 규칙 집합.
from __future__ import annotations

import re
from dataclasses import dataclass

from play_book_studio.config.packs import default_core_pack
from play_book_studio.retrieval.query import (
    detect_out_of_corpus_version,
    detect_unsupported_product,
    has_doc_locator_intent,
    has_hosted_control_plane_signal,
    has_logging_ambiguity,
    has_multiple_entity_ambiguity,
    has_postinstall_doc_locator_ambiguity,
    has_rbac_intent,
    has_security_doc_locator_ambiguity,
    has_update_doc_locator_ambiguity,
)

DEFAULT_CORE_PACK = default_core_pack()

GREETING_RE = re.compile(
    r"^\s*(안녕(?:하세요)?|하이|ㅎㅇ|hello|hi|hey|반가워|반갑습니다)(?:[!?.~\s]*)$",
    re.IGNORECASE,
)
THANKS_RE = re.compile(
    r"^\s*(고마워|감사(?:합니다|해요)?|thanks|thank you)(?:[!?.~\s]*)$",
    re.IGNORECASE,
)
FAREWELL_RE = re.compile(
    r"^\s*(잘가|바이|bye|수고해|나중에 봐|이따 봐)(?:[!?.~\s]*)$",
    re.IGNORECASE,
)
IDENTITY_RE = re.compile(
    r"^\s*(넌 누구야|너 누구야|누구세요|정체가 뭐야|뭐하는 챗봇이야|뭐하는 봇이야)(?:[!?.~\s]*)$",
    re.IGNORECASE,
)
CAPABILITY_RE = re.compile(
    r"(이 챗봇|너|당신|봇).*(뭐 할 수|무엇을 할 수|뭘 도와|도와줄 수)|"
    r"(뭐 할 수 있어|무엇을 할 수 있어|사용법이 뭐야|어떤 질문을 할 수 있어)",
    re.IGNORECASE,
)
OCP_GENERAL_ROLE_RE = re.compile(
    r"(오픈\s*시프트|오픈시프트|openshift|(?<![a-z0-9])ocp(?![a-z0-9])).*(실무|현업|현실|주로|보통|어디에|무슨 기능|어떤 기능|어떻게 쓰|어떻게 사용)",
    re.IGNORECASE,
)
OCP_BASIC_INTRO_RE = re.compile(
    r"^\s*((오픈\s*시프트|오픈시프트|openshift|(?<![a-z0-9])ocp(?![a-z0-9]))\s*(가|는|란|이란)?\s*(뭐야|뭔데|무엇|뭐지|소개해|개요를 알려|개요 알려|쉽게 설명해))[\?!.~\s]*$",
    re.IGNORECASE,
)
OCP_LEARNING_ADVICE_RE = re.compile(
    r"(오픈\s*시프트|오픈시프트|openshift|(?<![a-z0-9])ocp(?![a-z0-9])).*(잘하려면|잘 하려면|공부|배우|익히|입문|처음 시작|배경지식|기본기|마인드|어려워|어떻게 해야)",
    re.IGNORECASE,
)
TECHNICAL_HINT_RE = re.compile(
    r"(오픈\s*시프트|오픈시프트|openshift|(?<![a-z0-9])ocp(?![a-z0-9])|kubernetes|쿠버네티스|oc\s|pod|deployment|route|ingress|operator|etcd|rbac|namespace|네임스페이스|이름공간|yaml|pipeline|tekton|prometheus|alertmanager|node|노드|cluster|클러스터|image|images|registry|레지스트리|이미지|저장소|(?<![a-z0-9])pvc(?![a-z0-9])|(?<![a-z0-9])pv(?![a-z0-9])|persistent\s*volume|storageclass|storage\s*class|스토리지|볼륨|pending|imagepullbackoff|notready|crashloopbackoff)",
    re.IGNORECASE,
)
OCP_OPERATIONAL_ENTITY_RE = re.compile(
    r"\b(?:oc|kubectl|ccoctl|pod|pods|project|projects|namespace|namespaces|application|app|"
    r"deployment|route|ingress|operator|etcd|csr|oauth|machine|machineset|machineconfig|"
    r"machineconfigpool|mcp|imagestream|image|registry|api-resource|api-resources|secret|"
    r"configmap|node|nodes|pvc|pv|storageclass|gateway|insights|must-gather)\b|"
    r"프로젝트|애플리케이션|앱|파드|포드|네임스페이스|라우트|인그레스|오퍼레이터|"
    r"머신\s*세트|머신셋|인증서|토큰|레지스트리|이미지|API\s*리소스|지원되는 API|"
    r"로그|이벤트|CSR|OAuth|etcd|클러스터|노드|현재\s*선택된|현재\s*프로젝트",
    re.IGNORECASE,
)
OCP_OPERATIONAL_ACTION_RE = re.compile(
    r"어떻게|무슨|어떤|명령|명령어|확인|조회|보기|봐|목록|상태|생성|만들|등록|"
    r"삭제|제거|설정|변경|적용|수집|승인|업로드|추출|준비|점검|배포|활성화|"
    r"비활성화|가져와|가져오|바꿔|진행",
    re.IGNORECASE,
)
OCP_OPERATIONAL_PHRASE_RE = re.compile(
    r"새\s*프로젝트|새\s*애플리케이션|현재\s*선택된\s*프로젝트|현재\s*프로젝트\s*상태|"
    r"CSR\s*승인|지원되는\s*API\s*리소스|API\s*리소스\s*목록|Pod\s*로그|"
    r"Pod\s*목록|클러스터\s*이벤트|클러스터\s*진단|pull\s*secret|원격\s*상태\s*보고",
    re.IGNORECASE,
)
V016_OPERATIONAL_OVERRIDE_RE = re.compile(
    r"(?<![a-z0-9])(?:pdb|poddisruptionbudget|hpa|horizontalpodautoscaler|vpa|verticalpodautoscaler|hsts|localvolume|localvolumeset|localvolumediscovery)(?![a-z0-9])|"
    r"Local\s*Storage\s*Operator|Vertical\s*Pod\s*Autoscaler\s*Operator|로컬\s*스토리지|중단\s*예산|스케일링\s*정책|도메인별\s*HSTS",
    re.IGNORECASE,
)
OBSERVABILITY_COMPARE_RE = re.compile(
    r"(monitoring|모니터링).*(logging|로깅).*(observability|관측|옵저버빌리티).*(구분|차이|설명|비교)"
    r"|(?:구분|차이|설명|비교).*(monitoring|모니터링).*(logging|로깅).*(observability|관측|옵저버빌리티)",
    re.IGNORECASE,
)


def _friendly_intro_answer() -> str:
    return (
        "답변: 안녕하세요. 저는 OCP PlayBook 챗봇입니다. "
        "OpenShift 개념 설명, 운영 절차, 트러블슈팅을 문서 근거와 함께 가이드 형태로 안내합니다. "
        "편하게 질문해 주세요."
    )


def _ocp_learning_advice_answer() -> str:
    return (
        "답변: 오픈시프트를 잘하려면 먼저 리눅스 기본기, 컨테이너와 이미지, 쿠버네티스 핵심 리소스(Pod, Deployment, Service, Ingress)부터 익히는 편이 좋습니다. "
        "그다음에는 oc CLI, 로그와 이벤트 확인, 배포·롤백·스케일링, 프로젝트와 RBAC, 업데이트와 백업 같은 운영 절차를 손으로 반복해 보는 것이 가장 효과적입니다. "
        "원하면 입문 순서를 학습 로드맵처럼 나눠서 안내하겠습니다."
    )

def _looks_like_ocp_operational_question(query: str) -> bool:
    normalized = (query or "").strip()
    if not normalized:
        return False
    if V016_OPERATIONAL_OVERRIDE_RE.search(normalized):
        return True
    if OCP_OPERATIONAL_PHRASE_RE.search(normalized):
        return True
    return bool(OCP_OPERATIONAL_ENTITY_RE.search(normalized) and OCP_OPERATIONAL_ACTION_RE.search(normalized))


@dataclass(slots=True)
class RoutedResponse:
    route: str
    answer: str


def route_non_rag(
    query: str,
    *,
    corpus_label: str = DEFAULT_CORE_PACK.product_label,
    corpus_version: str = DEFAULT_CORE_PACK.version,
    allow_unsupported_product: bool = False,
) -> RoutedResponse | None:
    normalized = (query or "").strip()
    if not normalized:
        return None

    ocp_operational_question = _looks_like_ocp_operational_question(normalized)

    if GREETING_RE.match(normalized):
        return RoutedResponse(route="smalltalk", answer=_friendly_intro_answer())
    if THANKS_RE.match(normalized):
        return RoutedResponse(
            route="smalltalk",
            answer="답변: 필요하면 이어서 질문해 주세요. 지금 주제에서 실행 예시나 주의사항까지 같이 정리해 드릴 수 있습니다.",
        )
    if FAREWELL_RE.match(normalized):
        return RoutedResponse(
            route="smalltalk",
            answer="답변: 여기까지 보시죠. 필요하면 다시 들어와서 이어서 질문하시면 됩니다.",
        )
    if IDENTITY_RE.match(normalized):
        return RoutedResponse(
            route="meta",
            answer=(
                "답변: 저는 OCP PlayBook 챗봇입니다. "
                "OpenShift 문서를 바탕으로 개념 설명, 운영 절차, 트러블슈팅을 실행 가이드 형태로 안내합니다."
            ),
        )
    if ocp_operational_question or TECHNICAL_HINT_RE.search(normalized):
        return None
    if CAPABILITY_RE.search(normalized):
        return RoutedResponse(
            route="meta",
            answer=(
                "답변: 저는 OpenShift 개념 설명, 운영 절차, 트러블슈팅, 관련 명령 예시를 안내할 수 있습니다. "
                "가벼운 인사나 입문 질문도 받을 수 있고, 근거가 필요한 실무 질문은 문서를 찾아 가이드 형태로 답합니다."
            ),
        )
    if OCP_LEARNING_ADVICE_RE.search(normalized):
        return None
    # broad intro는 official overview/architecture hit를 붙여 답해야 하므로
    # 하드코딩 안내문으로 종료하지 않고 retrieval로 넘긴다.
    if OCP_BASIC_INTRO_RE.match(normalized):
        return None
    # broad role/usage intro도 official docs hit를 붙여 answer해야 하므로
    # 하드코딩 소개문으로 끊지 않고 retrieval로 넘긴다.
    if OCP_GENERAL_ROLE_RE.search(normalized):
        return None
    if not ocp_operational_question and has_logging_ambiguity(normalized):
        return RoutedResponse(
            route="clarification",
            answer=(
                "답변: 어떤 로그를 보는지 먼저 정해야 합니다. 애플리케이션, 인프라, 감사 로그 중 어떤 건가요?"
            ),
        )
    if not ocp_operational_question and has_security_doc_locator_ambiguity(normalized):
        return RoutedResponse(
            route="clarification",
            answer=(
                "답변: 어떤 보안 문제인지 범위를 먼저 정해야 합니다. 플랫폼 보안, 인증·권한, 네트워크 보안 중 어디부터 볼까요?"
            ),
        )
    if (
        not ocp_operational_question
        and has_multiple_entity_ambiguity(normalized)
        and not OBSERVABILITY_COMPARE_RE.search(normalized)
    ):
        return RoutedResponse(
            route="clarification",
            answer=(
                "답변: 지금은 대상이 여러 개라 범위를 먼저 정하는 편이 좋습니다. 하나씩 질문해 주시겠어요?"
            ),
        )
    if not ocp_operational_question and has_update_doc_locator_ambiguity(normalized):
        return RoutedResponse(
            route="clarification",
            answer=(
                "답변: 지금은 업데이트 범위가 불명확합니다. 현재 버전, 목표 버전, 단일 클러스터 업그레이드인지부터 확인해 주시겠어요?"
            ),
        )
    if not ocp_operational_question and has_postinstall_doc_locator_ambiguity(normalized):
        return RoutedResponse(
            route="clarification",
            answer=(
                "답변: 설치 후 무엇을 먼저 할지 작업 범위를 먼저 정해야 합니다. 네트워크, 보안·인증, 레지스트리·스토리지, 노드·머신셋, 모니터링 중 어디부터 볼까요?"
            ),
        )
    out_of_corpus_version = detect_out_of_corpus_version(normalized, corpus_version=corpus_version)
    if out_of_corpus_version is not None:
        return RoutedResponse(
            route="no_answer",
            answer=(
                f"답변: 현재 코퍼스는 {corpus_label} {corpus_version} 기준이라 {out_of_corpus_version} 버전 정보는 근거로 답할 수 없습니다."
            ),
        )
    unsupported_product = detect_unsupported_product(normalized)
    if unsupported_product is not None and not allow_unsupported_product:
        return RoutedResponse(
            route="no_answer",
            answer=(
                "답변: 현재 코퍼스에는 해당 외부 제품 또는 리소스 절차를 답할 근거가 없습니다."
            ),
        )
    if has_doc_locator_intent(normalized) or has_rbac_intent(normalized):
        return None
    if has_hosted_control_plane_signal(normalized):
        return None
    if ocp_operational_question:
        return None
    return None
