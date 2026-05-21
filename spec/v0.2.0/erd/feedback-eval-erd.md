# Feedback and Eval ERD Draft

## Goal

Capture user feedback, retrieval failures, benchmark candidates, and eval run history so RAG quality can improve continuously.

## Candidate Tables

- `answer_feedback`
- `retrieval_failure_cases`
- `benchmark_candidates`
- `eval_runs`
- `eval_run_items`

## answer_feedback

Stores user rating and optional reason.

Key fields:

- `answer_id`
- `session_id`
- `owner_user_id`
- `rating`
- `reason_tags`
- `feedback_text`
- `created_at`

## retrieval_failure_cases

Stores structured failure evidence.

Key fields:

- `query`
- `route`
- `query_analysis`
- `retrieved_chunk_ids`
- `selected_citations`
- `failure_type`
- `created_at`

## benchmark_candidates

Stores reviewed candidates for future eval sets.

Key fields:

- `source_failure_case_id`
- `query`
- `expected_source_type`
- `expected_objects`
- `expected_commands`
- `review_status`

## Notes

Feedback must not mutate production corpus automatically. It creates reviewed work candidates.
