from __future__ import annotations

from pathlib import Path

from play_book_studio.evals import user_upload_rag_eval
from play_book_studio.evals.user_upload_rag_eval import EvalCase


REPO_ROOT = Path(__file__).resolve().parents[1]


class DummySession:
    pass


def test_user_upload_rag_smoke_cases_are_loadable() -> None:
    suite, cases = user_upload_rag_eval._load_cases(
        REPO_ROOT / "spec/v0.1.4/user_upload_eval/user-upload-rag-smoke-cases.json"
    )

    assert suite["suite_id"] == "user-upload-rag-smoke-v1"
    assert [case.case_id for case in cases] == [
        "upload-ci-sequence",
        "upload-scc-overview",
        "upload-imagestream-overview",
    ]
    assert all(case.require_upload_citation for case in cases)


def test_user_upload_rag_default_50_cases_are_loadable() -> None:
    suite, cases = user_upload_rag_eval._load_cases(
        REPO_ROOT / "spec/v0.1.4/user_upload_eval/user-upload-rag-50-cases.json"
    )

    assert suite["suite_id"] == "user-upload-rag-50-v1"
    assert len(cases) == 50
    assert len({case.case_id for case in cases}) == 50
    assert all(case.question for case in cases)
    assert all(case.require_upload_citation for case in cases)


def test_user_upload_rag_eval_forces_upload_only_source_scope(monkeypatch) -> None:
    captured = {}

    def fake_request_json(session, *, method, url, timeout_seconds, json_payload=None):
        del session, method, url, timeout_seconds
        captured.update(json_payload or {})
        return {
            "answer": "The uploaded document explains the CI sequence with PipelineRun and registry push details.",
            "answer_source": "pbs_rag",
            "response_kind": "rag",
            "citations": [
                {
                    "book_slug": "uploaded-documents",
                    "viewer_path": "/uploads/documents/doc-ci/index.html#chunk-ci",
                    "section": "CI sequence",
                    "excerpt": "PipelineRun pushes an image to the registry.",
                }
            ],
        }

    monkeypatch.setattr(user_upload_rag_eval, "_request_json", fake_request_json)

    result = user_upload_rag_eval._run_case(
        DummySession(),
        EvalCase(
            case_id="upload-ci",
            topic="ci",
            question="What is the CI sequence?",
            expected_source_keywords=("CI",),
            required_answer_terms=("PipelineRun",),
            min_citations=1,
            min_answer_chars=20,
            require_upload_citation=True,
        ),
        base_url="http://pbs.example.test",
        repository_id="repo-1",
        timeout_seconds=5,
        suite_id="suite",
    )

    assert captured["enabled_source_scopes"] == ["user_upload"]
    assert captured["active_repository_id"] == "repo-1"
    assert result["evaluation"]["verdict"] == "pass"


def test_user_upload_rag_eval_rejects_lightspeed_reference() -> None:
    case = EvalCase(
        case_id="upload-ci",
        topic="ci",
        question="What is the CI sequence?",
        expected_source_keywords=("CI",),
        required_answer_terms=(),
        min_citations=1,
        min_answer_chars=20,
        require_upload_citation=True,
    )

    scored = user_upload_rag_eval._score_case(
        case,
        {
            "answer": "The uploaded document explains the CI sequence.",
            "answer_source": "pbs_rag",
            "response_kind": "rag",
            "citations": [
                {
                    "book_slug": "uploaded-documents",
                    "viewer_path": "/uploads/documents/doc-ci/index.html#chunk-ci",
                    "section": "CI sequence",
                    "excerpt": "CI sequence",
                }
            ],
            "related_links": [{"href": "/external/lightspeed/conversations/abc"}],
        },
    )

    assert scored["verdict"] == "review"
    assert "external_lightspeed_reference_present" in scored["failure_reasons"]
