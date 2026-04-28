import { useState } from 'react';
import type { ChatCitation, ChatRelatedLink, ViewerDocumentResponse } from '../lib/runtimeApi';
import { loadSourceMeta, loadViewerDocument, type SourceMetaResponse } from '../lib/runtimeApi';
import { AssistantAnswer } from './workspace/WorkspaceAnswer';
import CourseChatArtifacts from './CourseChatArtifacts';
import type { CourseChatResponse } from '../lib/courseApi';

type ViewerPreviewState =
  | { kind: 'empty' }
  | { kind: 'loading'; title: string }
  | {
      kind: 'viewer';
      title: string;
      subtitle: string;
      meta: SourceMetaResponse;
      document: ViewerDocumentResponse;
    }
  | { kind: 'error'; title: string; message: string };

function noop(): void {
  return undefined;
}

function neverFavorite(): boolean {
  return false;
}

export default function CourseChatWorkspaceAnswer({
  response,
  onSuggestedQuery,
}: {
  response: CourseChatResponse;
  onSuggestedQuery?: (query: string) => void;
}) {
  const [preview, setPreview] = useState<ViewerPreviewState>({ kind: 'empty' });

  async function openViewerPreview(viewerPath: string, title: string): Promise<void> {
    if (!viewerPath) {
      setPreview({ kind: 'empty' });
      return;
    }
    setPreview({ kind: 'loading', title });
    try {
      const meta = await loadSourceMeta(viewerPath);
      const document = await loadViewerDocument(meta.viewer_path || viewerPath);
      setPreview({
        kind: 'viewer',
        title: meta.book_title || title,
        subtitle: meta.section_path_label || meta.section || '',
        meta,
        document,
      });
    } catch (caught) {
      setPreview({
        kind: 'error',
        title,
        message: caught instanceof Error ? caught.message : 'Failed to open viewer preview',
      });
    }
  }

  function handleCitationClick(citation: ChatCitation): void {
    void openViewerPreview(citation.viewer_path, citation.source_label || citation.book_title || citation.section);
  }

  function handleRelatedLinkClick(link: ChatRelatedLink): void {
    void openViewerPreview(link.href, link.label);
  }

  return (
    <div className="course-chat-workspace-shell">
      <div className="course-chat-workspace-answer">
        <AssistantAnswer
          content={response.answer}
          citations={response.citations ?? []}
          relatedLinks={response.related_links ?? []}
          relatedSections={response.related_sections ?? []}
          visionMode="guided_tour"
          primarySourceLane="study_docs_course_runtime"
          primaryBoundaryTruth="internal_course_runtime"
          primaryRuntimeTruthLabel="Study-docs Course"
          primaryBoundaryBadge="Internal Course"
          primaryPublicationState="internal"
          primaryApprovalState="course_reviewed"
          onCitationClick={handleCitationClick}
          onRelatedLinkClick={handleRelatedLinkClick}
          onToggleFavoriteLink={noop}
          onCheckSectionLink={noop}
          isFavoriteLink={neverFavorite}
          isCheckedSectionLink={neverFavorite}
        />
        {response.suggested_queries?.length ? (
          <div className="course-chat-suggested">
            <span>다음 step 질문</span>
            <div className="course-chat-suggested-list">
              {response.suggested_queries.map((suggestedQuery, index) => (
                <button
                  key={`course-suggested-${index}`}
                  type="button"
                  onClick={() => onSuggestedQuery?.(suggestedQuery)}
                  disabled={!onSuggestedQuery}
                >
                  {suggestedQuery}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        <CourseChatArtifacts artifacts={response.artifacts} />
      </div>

      {preview.kind !== 'empty' ? (
        <aside className="course-chat-viewer-panel">
          {preview.kind === 'loading' ? (
            <div className="course-chat-viewer-state">Loading {preview.title}</div>
          ) : null}
          {preview.kind === 'error' ? (
            <div className="course-chat-viewer-state">
              <strong>{preview.title}</strong>
              <span>{preview.message}</span>
            </div>
          ) : null}
          {preview.kind === 'viewer' ? (
            <>
              <div className="course-chat-viewer-head">
                <strong>{preview.title}</strong>
                <span>{preview.subtitle}</span>
              </div>
              {preview.document.inline_styles.map((styleText, index) => (
                <style key={`course-viewer-style-${index}`}>{styleText}</style>
              ))}
              <div
                className={`viewer-root ${preview.document.body_class_name || ''}`}
                dangerouslySetInnerHTML={{ __html: preview.document.html }}
              />
            </>
          ) : null}
        </aside>
      ) : null}
    </div>
  );
}
