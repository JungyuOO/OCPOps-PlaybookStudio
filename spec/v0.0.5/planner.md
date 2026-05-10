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
