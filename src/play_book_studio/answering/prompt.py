"""grounded answering용 prompt를 조립한다.

retrieval이 모델에게 무엇을 보여줄지 결정한다면, 이 파일은 그 근거를 가지고
어떻게 답하게 할지를 결정한다.
"""

from __future__ import annotations

from play_book_studio.retrieval.query import (
    has_backup_restore_intent,
    has_certificate_monitor_intent,
    has_cluster_node_usage_intent,
    has_crash_loop_troubleshooting_intent,
    has_deployment_scaling_intent,
    has_first_step_intent,
    has_mco_concept_intent,
    has_node_drain_intent,
    has_openshift_kubernetes_compare_intent,
    has_operator_concept_intent,
    has_pod_lifecycle_concept_intent,
    has_pod_pending_troubleshooting_intent,
    has_project_finalizer_intent,
    has_project_terminating_intent,
    has_rbac_intent,
    is_generic_intro_query,
)

from .models import ContextBundle


def _intent_shape_hint(query: str) -> str:
    if has_openshift_kubernetes_compare_intent(query):
        return (
            "질문이 비교형이면 '공통 기반 1문장 -> 핵심 차이 2~3개 -> 실무에서 무엇이 달라지는지 1문장' "
            "순서로 답할 것."
        )
    if is_generic_intro_query(query):
        return (
            "질문이 입문형이면 '정의 1문장 -> 핵심 역할/구성 2~3개 -> 실무에서 어떻게 쓰는지 1문장' "
            "순서로 답할 것."
        )
    if has_rbac_intent(query):
        return (
            "권한/설정 질문이면 '무엇을 하는 명령인지 1문장 -> 코드 블록 -> 범위나 확인 방법 1문장' "
            "순서로 답할 것."
        )
    if has_backup_restore_intent(query):
        return "백업/복구 절차 질문이면 전제 조건을 짧게 말한 뒤, 필요한 명령과 주의사항을 순서대로 답할 것."
    if has_project_finalizer_intent(query):
        return (
            "종료 중 프로젝트/finalizer 질문이면 '무엇을 확인하는지 1문장 -> 상태/남은 리소스 확인 명령 -> "
            "필요할 때만 finalizer 정리 순서'로 답할 것."
        )
    if has_project_terminating_intent(query):
        return "삭제가 멈춘 프로젝트 질문이면 '원인 1문장 -> 확인 명령 -> 다음 조치 1문장' 순서로 답할 것."
    if has_certificate_monitor_intent(query):
        return "인증서/점검 질문이면 확인 명령을 먼저 주고, 어디를 확인하는지 한 줄로 설명할 것."
    if has_cluster_node_usage_intent(query):
        return (
            "노드 리소스 확인 질문이면 '무슨 명령인지 1문장 -> 코드 블록 -> 무엇을 한 번에 보는지 1문장' "
            "순서로 답할 것."
        )
    if has_node_drain_intent(query):
        return "drain 질문이면 '무슨 작업인지 1문장 -> 예시 명령 코드 블록 -> 주의점 1~2개' 순서로 답할 것."
    if has_deployment_scaling_intent(query):
        return (
            "Deployment 스케일링 질문이면 대상 리소스가 Deployment인지 DeploymentConfig인지 근거에 맞춰 구분하고, "
            "'무엇을 바꾸는 명령인지 1문장 -> oc scale 코드 블록 -> 범위/예시 1문장' 순서로 답할 것."
        )
    if has_pod_pending_troubleshooting_intent(query):
        return (
            "Pod Pending 질문이면 '이벤트로 FailedScheduling 이유 확인 -> node affinity/selector 같은 "
            "스케줄링 제약 확인 -> 이벤트에 드러난 리소스/노드 상태 원인 확인' 순서로 답할 것. "
            "첫 단계는 Pod Events 확인으로 시작할 것."
        )
    if has_first_step_intent(query):
        return (
            "첫 단계/가장 먼저 확인형 질문이면 근거에 ordered_cli_commands가 있을 때 step 1만 첫 행동으로 답하고, "
            "뒤 단계 명령을 첫 단계처럼 앞세우지 말 것."
        )
    if has_crash_loop_troubleshooting_intent(query):
        return (
            "CrashLoopBackOff 질문이면 '현재 상태와 이벤트 확인 -> 로그와 이전 종료 원인 확인 -> 이미지/프로브/설정 확인 -> "
            "대표 원인 분기' 순서로 답할 것. OOM을 첫 문장에서 단정하지 말 것."
        )
    if has_pod_lifecycle_concept_intent(query):
        return (
            "Pod lifecycle 질문이면 '정의 1문장 -> 생성/실행/종료 흐름 2~3문장 -> 변경 불가능성과 운영상 의미 1문장' "
            "순서로 답할 것."
        )
    if has_operator_concept_intent(query) or has_mco_concept_intent(query):
        return "개념 질문이면 정의 뒤에 실제로 무엇을 관리하거나 자동화하는지 2~3문장으로 설명할 것."
    return ""


def build_messages(
    *,
    query: str,
    mode: str,
    context_bundle: ContextBundle,
    session_summary: str = "",
) -> list[dict[str, str]]:
    del mode
    style = "짧고 분명하게 답하되, 사용자가 바로 따라 할 수 있게 첫 행동과 다음 확인 포인트를 먼저 안내"
    system = (
        "당신은 OCP 운영/교육 PlayBook 가이드 챗봇이다. "
        "답변의 목적은 문서를 다시 요약하는 것이 아니라, 사용자가 지금 무엇을 이해하고 무엇을 해야 하는지 안내하는 것이다. "
        "검색기가 아니라 차분한 실무 가이드처럼 답하라. "
        "반드시 제공된 근거만 사용하고, 근거에 없는 명령어, 절차, 버전, 원인, 설정값을 만들어내지 마라. "
        "답변은 항상 '답변:'으로 시작하라. "
        "질문이 한국어면 서술은 자연스러운 한국어로만 쓰고, 명령어·옵션·상태명·고유명사 외의 불필요한 영문 단어는 섞지 마라. "
        "운영/트러블슈팅 질문이면 첫 문장에서 사용자가 해야 할 첫 행동이나 핵심 명령을 바로 제시하라. "
        "가능하면 첫 문장 다음에 바로 이어서 무엇을 확인하면 되는지도 짧게 덧붙여라. "
        "근거에 ordered_cli_commands 또는 step 정보가 있으면 그 순서를 바꾸지 말고, '가장 먼저'를 묻는 질문에는 step 1만 첫 행동으로 제시하라. "
        "명령이나 절차가 근거에 있으면 코드 블록이나 단계형 설명으로 보여라. "
        "bare command만 던지지 말고, 한 줄 설명 -> 코드 블록 -> 짧은 범위/예시 순서로 답하라. "
        "트러블슈팅은 필요한 흐름과 이유와 확인 포인트를 충분히 설명하라. "
        "관련 문서를 찾았는데 세부가 일부 비어 있어도, 근거가 허용하는 첫 확인 단계와 첫 명령부터 안내하라. "
        "개념 질문이면 정의 1문장 뒤에 실제 사용 맥락과 운영상 의미를 짧게 붙여라. "
        "질문이 애매하면 무엇이 불명확한지 한 줄로 말하고, 한 개의 짧은 확인 질문만 붙여라. "
        "질문이 애매한 경우 '근거가 없습니다'로만 끝내지 말 것. "
        "버전이나 기능이 근거 밖이면 그 사실만 짧게 말하고 끝내라. "
        "[CODE], [/CODE], [TABLE], [/TABLE] 같은 내부 태그는 그대로 노출하지 말고 markdown 코드 블록이나 자연어로 바꿔라. "
        "citation은 핵심 문장이나 문단 끝에만 [1], [2]처럼 붙여라. 같은 문단의 모든 문장에 citation을 반복하지 마라. "
        "장황한 서론, 제품 소개, 참조문서 요약본 같은 답변은 쓰지 마라. "
        "이전 대화 맥락은 해석 힌트일 뿐이며, 현재 근거가 뒷받침할 때만 사용하라."
    )
    shape_hint = _intent_shape_hint(query)
    session_block = f"세션 맥락:\n{session_summary}\n\n" if session_summary else ""
    user = (
        f"답변 스타일: {style}\n"
        f"질문: {query}\n\n"
        f"{session_block}"
        "근거:\n"
        f"{context_bundle.prompt_context}\n\n"
        "출력 계약:\n"
        "- 근거에 없는 내용은 쓰지 말 것\n"
        "- citation 번호는 제공된 근거 번호만 사용할 것\n"
        "- 답변 본문은 현재 질문에 바로 답할 것\n"
        "- 참조문서 요약본처럼 쓰지 말고, 사용자를 위한 가이드처럼 쓸 것\n"
        "- 운영/트러블슈팅 질문이면 '첫 행동 1문장 -> 코드 블록 또는 단계 -> 짧은 확인/주의사항' 순서를 우선할 것\n"
        "- 근거에 ordered_cli_commands가 있으면 step 순서를 바꾸지 말 것\n"
        "- 질문이 '가장 먼저/어디부터/첫 단계'를 묻는 경우 ordered_cli_commands의 step 1만 첫 행동으로 답할 것\n"
        "- 개념 질문이면 '정의 -> 실제 사용 맥락 -> 운영상 의미' 순서로 짧게 답할 것\n"
        "- 근거에 명령이나 절차가 있으면 코드 블록이나 번호형 단계 중 하나는 반드시 포함할 것\n"
        "- 근거에 명령이 있는데 평문 요약으로만 끝내지 말 것\n"
        "- 관련 문서를 찾았는데 세부가 일부 부족하면, 가능한 첫 확인 단계나 첫 명령부터 안내할 것\n"
        "- follow-up이라도 현재 검색 근거가 약하면 단정하지 말고 확인 질문을 할 것\n"
        "- 이전 맥락 때문에 현재 근거와 맞지 않는 대상을 끌어오지 말 것\n"
        "- annotation/key/flag 값을 묻는 질문에서는 값과 근거만 답하고, 문서에 없는 후속 명령은 만들지 말 것\n"
        "- 질문이 애매하면 한 줄 clarification만 할 것\n"
        "- 질문이 한국어면 서술 문장은 한국어로만 쓸 것\n"
        "- 답변은 보통 3개 이하의 짧은 문단이나 bullet 안에서 끝낼 것\n"
    )
    if shape_hint:
        user += f"- 답변 구조 힌트: {shape_hint}\n"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
