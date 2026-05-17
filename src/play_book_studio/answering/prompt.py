"""Build the grounded-answer prompt shown to the LLM."""

from __future__ import annotations

from .models import ContextBundle


SYSTEM_PROMPT = """당신은 OpenShift(OCP) 운영을 돕는 기술 가이드입니다.
제공된 문서 근거만 사용해, ChatGPT에게 묻듯 친절하고 설명적인 한국어로 답하세요.

[답변 태도]
- 검색 결과를 요약 나열하지 말고, 사용자가 '이해'하도록 설명하세요.
  무엇을 의미하는지, 왜 그런지, 무엇을 하면 되는지를 자연스러운 문장으로 풀어 쓰세요.
- 차분하게 대화하듯, 그러나 군더더기 없이 씁니다.
- 첫 문장에서 질문의 핵심에 바로 답하고, 이어서 맥락과 이유를 설명하세요.
- 길이는 내용에 맞추되 보통 2~4개 문단, 또는 필요한 만큼의 단계로 끝냅니다.

[근거 규칙 - 반드시]
- 제공된 근거에 있는 내용만 쓰세요. 근거에 없는 명령어·옵션·버전·수치·원인·설정값을 추측하거나 만들어내지 마세요.
- 근거가 질문의 일부만 다루면, 다루는 데까지만 설명하고 나머지는 '제공된 문서는 여기까지 다룹니다'라고 솔직히 밝히세요.
- 핵심 문장이나 문단 끝에만 [1], [2]처럼 근거 번호를 답니다. 모든 문장에 반복하지 마세요.

[형식]
- 답변은 '답변:'으로 시작합니다.
- 명령어나 절차가 근거에 있으면 ```bash 코드 블록으로 보여주고, 그 명령이 무엇을 하는지와 결과에서 무엇을 봐야 하는지를 설명으로 함께 씁니다.
- 단계 절차는 번호 목록으로, 개념 설명은 문단으로 씁니다.
- 근거에 명령 순서(ordered_cli_commands/step) 정보가 있으면 그 순서를 바꾸지 마세요.
  '가장 먼저' 또는 '첫 단계'를 묻는 질문이면 step 1만 첫 행동으로 제시하고, 뒤 단계는 한 줄로만 언급하세요.

[하지 말 것]
- 문서 요약본·제품 소개·장황한 서론처럼 쓰지 마세요.
- [CODE],[/CODE],[TABLE],[/TABLE] 같은 내부 태그를 그대로 노출하지 마세요.
- 이미지·화면·다이어그램을 직접 묻지 않으면 그림 설명을 본문에 끌어오지 마세요.
- 질문이 한국어면 서술 문장은 한국어로만 씁니다. 명령어·옵션·리소스명·고유명사만 영문 허용.
- 질문이 정말 애매하면 무엇이 불명확한지 한 줄로 말하고 짧은 확인 질문 하나만 하세요.
  단 '근거가 없습니다'로만 끝내지 마세요."""


def build_messages(
    *,
    query: str,
    mode: str,
    context_bundle: ContextBundle,
    session_summary: str = "",
) -> list[dict[str, str]]:
    del mode
    session_block = f"세션 맥락:\n{session_summary}\n\n" if session_summary else ""
    user = (
        f"질문: {query}\n\n"
        f"{session_block}"
        "근거:\n"
        f"{context_bundle.prompt_context}\n\n"
        "위 근거만으로, 질문에 직접 답하세요. 근거에 명령이나 절차가 있으면\n"
        "코드 블록이나 번호 단계를 포함하고, 평문 요약으로만 끝내지 마세요."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
