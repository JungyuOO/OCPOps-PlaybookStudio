from play_book_studio.answering.router import route_non_rag


def test_security_ambiguity_asks_which_security_scope() -> None:
    routed = route_non_rag("보안 문제는 어디서 봐?")

    assert routed is not None
    assert routed.route == "clarification"
    assert "어떤 보안 문제" in routed.answer


def test_postinstall_ambiguity_asks_what_to_do_first() -> None:
    routed = route_non_rag("설치 후에 뭐 먼저 해야 해?")

    assert routed is not None
    assert routed.route == "clarification"
    assert "무엇을 먼저" in routed.answer


def test_observability_comparison_is_not_treated_as_ambiguous() -> None:
    assert route_non_rag("Monitoring, Logging, Observability를 운영 관점에서 구분해서 설명해줘") is None
