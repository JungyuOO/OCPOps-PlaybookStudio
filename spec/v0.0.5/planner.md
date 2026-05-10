# v0.0.5 Planner - Studio Repository Scope Clear

## Context

Studio can open directly with `workspace.activeSourceId=repository:<id>` restored from local storage. In that state the chat scope badge shows `Repository-scoped RAG` and the repository title, for example `Official Docs`, but the badge only renders an X/clear control for `Document-scoped RAG`.

## Goal

Let users clear repository-scoped RAG from the Studio chat surface without changing the existing Library-to-Studio repository/document handoff behavior.

## Scope

- Add a clear action for repository-scoped RAG in Studio.
- Keep the existing document-scope clear behavior: clearing a document scope should fall back to the active repository scope.
- Clearing repository scope should clear active repository, active document, active category, and the corresponding local storage-backed state through the existing React effects.
- After repository scope is cleared, chat requests must not send `activeRepositoryId` or `activeDocumentId`.

## Non-goals

- No hardcoded repository names such as `Official Docs`.
- No changes to retrieval ranking, chunking, or answer generation.
- No changes to Library repository/document selection flows beyond preserving compatibility.

## Verification Plan

- Build the web app with `npm --prefix apps/web run build`.
- Inspect the Studio chat scope badge for both repository-scoped and document-scoped states.
- Confirm the clear button is rendered for repository-scoped RAG and clears the payload scope fields by state behavior.

## Completion Notes

- Implemented in `apps/web/src/pages/WorkspacePage.tsx`.
- Repository-scoped RAG now renders the same clear affordance area as document scope.
- Clicking `Clear repository scope` clears `activeSourceId`, `activeDocumentId`, document title, category key, and category label.
- Existing document scope clear behavior remains unchanged: it removes only the document/category scope and leaves the repository scope active.

## Verification Results

- Passed: `npm --prefix apps/web run build`.
- Passed: rebuilt local web container with `docker compose up -d --build web`.
- Passed: Playwright Studio smoke at `http://localhost:8080/studio`:
  - Set `workspace.activeSourceId=repository:319859c0-982b-4810-b3ca-38c3a101170c`.
  - Confirmed `Repository-scoped RAG / Official Docs` shows `Clear repository scope`.
  - Clicked clear and confirmed the scope badge disappeared and `workspace.activeSourceId` was removed.
  - Set repository + document scope and confirmed `Clear document scope` still falls back to `Repository-scoped RAG`.
- Known gap: `npm --prefix apps/web run lint` still fails on pre-existing unrelated React Compiler/eslint issues in viewer, course timeline, terminal, answer, and wiki files.
