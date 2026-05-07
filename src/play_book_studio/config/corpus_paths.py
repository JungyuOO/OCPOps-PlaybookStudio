"""Shared local seed/import paths.

These paths describe local corpus inputs only. Runtime code should prefer
PostgreSQL/Qdrant/storage after the seed data has been imported.
"""

from __future__ import annotations

from pathlib import Path


CORPUS_ROOT = Path("corpus")
CORPUS_DATA_DIR = CORPUS_ROOT / "data"
CORPUS_MANIFESTS_DIR = CORPUS_ROOT / "manifests"
COURSE_SEED_MANIFESTS_DIR = CORPUS_MANIFESTS_DIR / "course"
DEMO_MANIFESTS_DIR = CORPUS_MANIFESTS_DIR / "demo"
EVAL_MANIFESTS_DIR = CORPUS_MANIFESTS_DIR / "eval"
OFFICIAL_MANIFESTS_DIR = CORPUS_MANIFESTS_DIR / "official"
CORPUS_SOURCES_DIR = CORPUS_ROOT / "sources"
KMSC_SOURCES_DIR = CORPUS_SOURCES_DIR / "kmsc"
OFFICIAL_SOURCES_DIR = CORPUS_SOURCES_DIR / "official"
OFFICIAL_IMPORTED_GOLD_DIR = OFFICIAL_SOURCES_DIR / "imported-gold"

COURSE_PBS_DIR = KMSC_SOURCES_DIR / "parsed-preview" / "course_pbs"
COURSE_PBS_MANIFESTS_DIR = COURSE_PBS_DIR / "manifests"
COURSE_PBS_ASSETS_DIR = COURSE_PBS_DIR / "assets"

STUDY_DOCS_DIR = KMSC_SOURCES_DIR / "raw"

OFFICIAL_GOLD_CORPUS_DIR = OFFICIAL_IMPORTED_GOLD_DIR / "gold_corpus_ko"
OFFICIAL_GOLD_MANUALBOOK_DIR = OFFICIAL_IMPORTED_GOLD_DIR / "gold_manualbook_ko"
OFFICIAL_SILVER_KO_DIR = OFFICIAL_IMPORTED_GOLD_DIR / "silver_ko"
OFFICIAL_GOLD_CHUNKS_PATH = OFFICIAL_GOLD_CORPUS_DIR / "chunks.jsonl"

COURSE_QA_CASES_PATH = COURSE_SEED_MANIFESTS_DIR / "course_qa_cases.jsonl"
COURSE_QA_ACCEPTED_CASES_PATH = COURSE_SEED_MANIFESTS_DIR / "course_qa_cases.accepted.jsonl"
COURSE_QA_REJECTED_CASES_PATH = COURSE_SEED_MANIFESTS_DIR / "course_qa_cases.rejected.jsonl"
COURSE_OPS_LEARNING_GOLDEN_CASES_PATH = COURSE_SEED_MANIFESTS_DIR / "course_ops_learning_golden_cases.jsonl"
COURSE_LEARNING_ROUTES_OVERRIDES_PATH = COURSE_SEED_MANIFESTS_DIR / "course_learning_routes_overrides.json"
COURSE_REVIEW_OVERRIDES_PATH = COURSE_SEED_MANIFESTS_DIR / "course_review_overrides.json"

ANSWER_EVAL_CASES_PATH = EVAL_MANIFESTS_DIR / "answer_eval_cases.jsonl"
ANSWER_EVAL_REALWORLD_CASES_PATH = EVAL_MANIFESTS_DIR / "answer_eval_realworld_cases.jsonl"
RAGAS_EVAL_CASES_PATH = EVAL_MANIFESTS_DIR / "ragas_eval_cases.jsonl"
PBS_CHAT_QUALITY_CASES_PATH = EVAL_MANIFESTS_DIR / "pbs_chat_quality_cases.jsonl"
PBS_CHAT_QUALITY_EXTENDED_CASES_PATH = EVAL_MANIFESTS_DIR / "pbs_chat_quality_extended_cases.jsonl"
READER_GRADE_SHADOW_SAMPLES_PATH = EVAL_MANIFESTS_DIR / "reader_grade_shadow_samples.json"
RETRIEVAL_BENCHMARK_CASES_PATH = EVAL_MANIFESTS_DIR / "retrieval_benchmark_cases.jsonl"
RETRIEVAL_EVAL_CASES_PATH = EVAL_MANIFESTS_DIR / "retrieval_eval_cases.jsonl"
RETRIEVAL_ROOT_CAUSE_CASES_PATH = EVAL_MANIFESTS_DIR / "retrieval_root_cause_cases.jsonl"
RETRIEVAL_SANITY_CASES_PATH = EVAL_MANIFESTS_DIR / "retrieval_sanity_cases.jsonl"
RETRIEVAL_SMOKE_QUERIES_PATH = EVAL_MANIFESTS_DIR / "retrieval_smoke_queries.jsonl"

OCP420_REPO_WIDE_SOURCE_MANIFEST_PATH = OFFICIAL_MANIFESTS_DIR / "ocp420_repo_wide_source_manifest.json"
OCP420_SOURCE_FIRST_FULL_REBUILD_MANIFEST_PATH = OFFICIAL_MANIFESTS_DIR / "ocp420_source_first_full_rebuild_manifest.json"
OCP_KO_4_20_APPROVED_MANIFEST_PATH = OFFICIAL_MANIFESTS_DIR / "ocp_ko_4_20_approved_ko.json"
OCP_KO_4_20_CORPUS_WORKING_SET_PATH = OFFICIAL_MANIFESTS_DIR / "ocp_ko_4_20_corpus_working_set.json"
OCP_KO_4_20_HTML_SINGLE_PATH = OFFICIAL_MANIFESTS_DIR / "ocp_ko_4_20_html_single.json"
OCP_KO_4_20_TRANSLATED_DRAFT_PATH = OFFICIAL_MANIFESTS_DIR / "ocp_ko_4_20_translated_ko_draft.json"
OCP_KO_4_20_TRANSLATED_DRAFT_ALL_RUNTIME_PATH = OFFICIAL_MANIFESTS_DIR / "ocp_ko_4_20_translated_ko_draft_all_runtime.json"
OCP_MULTIVERSION_HTML_SINGLE_CATALOG_PATH = OFFICIAL_MANIFESTS_DIR / "ocp_multiversion_html_single_catalog.json"

DEMO_SAFE_QUESTIONS_PATH = DEMO_MANIFESTS_DIR / "demo_safe_questions.jsonl"
DEMO_MULTITURN_SCENARIOS_PATH = DEMO_MANIFESTS_DIR / "demo_multiturn_scenarios.jsonl"
OCP420_DEMO_SIMULATOR_SCENARIOS_PATH = DEMO_MANIFESTS_DIR / "ocp420_demo_simulator_scenarios.jsonl"
OCP420_MULTITURN_LIVE_SCENARIOS_PATH = DEMO_MANIFESTS_DIR / "ocp420_multiturn_live_scenarios.jsonl"

COURSE_MANIFEST_PATH = COURSE_PBS_MANIFESTS_DIR / "course_v1.json"
COURSE_QA_REPORT_PATH = COURSE_PBS_MANIFESTS_DIR / "course_qa_report.json"
OPS_LEARNING_ANCHOR_AUDIT_PATH = COURSE_PBS_MANIFESTS_DIR / "ops_learning_anchor_audit_v1.json"
OPS_LEARNING_GUIDES_PATH = COURSE_PBS_MANIFESTS_DIR / "ops_learning_guides_v1.json"
OPS_LEARNING_CHUNKS_PATH = COURSE_PBS_MANIFESTS_DIR / "ops_learning_chunks_v1.jsonl"
