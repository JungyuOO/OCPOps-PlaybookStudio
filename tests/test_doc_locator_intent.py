from play_book_studio.answering.doc_locator_intent import is_document_sequence_query


def test_cross_document_operator_monitoring_question_is_sequence_query() -> None:
    assert is_document_sequence_query(
        "Operator 장애가 났을 때 monitoring과 operators 문서를 어떻게 같이 따라가야 하나?"
    )


def test_direct_document_lookup_is_not_sequence_query() -> None:
    assert not is_document_sequence_query("Operator 문제 해결 문서는 어디를 보면 돼?")
