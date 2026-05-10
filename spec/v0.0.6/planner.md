# v0.0.6 Planner - OCP Command Learning RAG Verification

## Context

The next quality gate is whether a beginner can learn OpenShift by asking Studio questions, receiving grounded command guidance, typing those commands in the terminal, and understanding the next step from the answer.

This must not become a fixed question-to-answer table. The system should keep generating answers from retrieved corpus chunks, command metadata, current context, and citations. Eval cases may define expected evidence and command terms, but runtime behavior must remain retrieval-grounded.

## Goal

Build a broad command-learning verification lane and use its failures to improve RAG retrieval, answer grounding, or chunk quality.

## Scope

- Add a v0.0.6 command-learning eval manifest with varied OCP command questions.
- Extend live Studio smoke validation so cases can require grounded answer terms and citation terms.
- Cover step-by-step learning flows, operational command lookup, troubleshooting, install/bootstrap, RBAC, nodes, pods, routes, storage, registry, MCO, certificates, and etcd.
- Use failures to decide whether query expansion/reranking/answer shaping/chunk audit must change.
- Record verification results and remaining failures in this planner.

## Non-goals

- No hardcoded final answers.
- No fixed expected-question to fixed-answer runtime mappings.
- No corpus reimport or rechunking unless eval evidence shows retrieval misses caused by chunk quality.

## Initial Verification Plan

- Run focused unit tests for smoke validation and command grounding.
- Run live Studio smoke against `http://localhost:8080` with the v0.0.6 command-learning manifest.
- If failures cluster around retrieval misses, inspect retrieval traces and chunk audit evidence before changing ranking or chunking.
- If failures are answer formatting/grounding only, fix answer contracts without changing corpus data.

## Work Log

- Added `corpus/manifests/eval/ocp_command_learning_v006_cases.jsonl` with 20 command-learning scenarios across namespace/project, pod events/logs, cluster operators, node drain/debug, etcd backup, install bootstrap, RBAC, routes/services, PVC, MCO, and certificates.
- Extended `studio_live_smoke` so eval rows can require answer terms, citation terms, forbidden terms, custom case files, and starter-question skipping.
- Added `retrieval.intent_profile` as a structured command-learning profile. This is not a fixed Q&A table; it extracts target object, task, primary command candidates, and evidence terms from the user query so retrieval can prefer relevant corpus chunks.
- Connected the intent profile to query expansion and retrieval scoring. Command-bearing chunks still need corpus evidence; the scorer now boosts hits containing the profile's target command/evidence and mildly penalizes unrelated command chunks.
- Added regression tests for command smoke validation, namespace list vs current-context distinction, clusteroperator/node/MCP routing, and profile coverage for previous logs, PVC, can-i, route/service, and etcd.

## Verification Results

- Unit regression: `pytest tests/test_chat_grounding_quality.py tests/test_answer_text_commands.py -q` -> `40 passed`.
- Runtime health: `curl.exe -s -i http://127.0.0.1:8080/api/health` -> `200 OK` after app rebuild.
- Live command-learning smoke:
  - Command: `python -m play_book_studio.evals.studio_live_smoke --base-url http://127.0.0.1:8080 --case-file corpus/manifests/eval/ocp_command_learning_v006_cases.jsonl --skip-starters --manifest-limit 0 --followups-per-case 0 --limit 0 --report-path reports/ocp_command_learning_v006_live_smoke.json`
  - Current result: `10/20` passed, `pass_rate=0.50`.

## Remaining Failures

The remaining failures are not a reason to hardcode answers. They point to the next RAG quality work:

- Generic CLI reference chunks still beat exact command chunks for some command lookups, for example namespace list and bootstrap wait.
- Some correct answer templates are stripped or weakened because the selected citation does not contain the exact command variant, for example `oc get service`, `oc get clusteroperators`, `oc adm uncordon`, and `--previous`.
- Multi-step workflows need better chunk adjacency or retrieval composition. Node drain should retrieve both drain and uncordon evidence, and etcd backup should keep `chroot /host` in the grounded sequence.
- Project terminating still falls into low-confidence clarification even though the corpus contains relevant Terminating namespace chunks; this needs retrieval trace inspection and likely query/rerank adjustment around `Terminating`, `oc get namespaces`, and `oc get namespace <name>`.

## Next Step

Before attempting another broad fix, inspect retrieval traces for the failing case IDs and decide whether the issue is candidate generation, reranker selection, citation eligibility, or answer-command stripping. If candidate generation is missing exact chunks, improve query expansion or chunk metadata. If candidates are present but not selected, tune intent-profile scoring or section-level diversification. If citations are correct but commands are stripped, fix answer grounding to preserve commands that are directly supported by citation command variants.
