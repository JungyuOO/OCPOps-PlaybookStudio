# Official Manifests

This folder contains official OpenShift source selection and rebuild manifests.

## Important Files

- `ocp_ko_4_20_approved_ko.json`: legacy active manifest; currently mostly
  `html-single`.
- `ocp_ko_4_20_corpus_working_set.json`: mixed working set.
- `ocp420_source_first_full_rebuild_manifest.json`: 29-document source-first
  rebuild manifest.
- `ocp420_repo_wide_source_manifest.json`: repo-wide source-first topic map.

## Rule

Before rebuilding official corpus data, state which manifest is the source of
truth. Do not mix HTML fallback and source-first inputs silently.

Current default settings still point at `ocp_ko_4_20_approved_ko.json`. Treat
the source-first manifests as candidates until the default, import job, and
tests are switched together.
