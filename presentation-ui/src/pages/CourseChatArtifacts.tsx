import { Link } from 'react-router-dom';
import { buildCourseAssetUrl } from '../lib/courseApi';

type ArtifactItem = Record<string, unknown>;

function text(value: unknown): string {
  return String(value || '').trim();
}

function publicText(value: unknown): string {
  return text(value)
    .replace(/\b(?:DSGN|TEST|CH|KMSC|COCP|RTER|PLAN|RESULT|FRONT)[-A-Z0-9]*\b/gi, '')
    .replace(/\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b/g, '')
    .replace(/\s+/g, ' ')
    .replace(/^[\s\-:_]+|[\s\-:_]+$/g, '');
}

function itemsOf(artifact: Record<string, unknown>): ArtifactItem[] {
  return Array.isArray(artifact.items) ? artifact.items.filter((item): item is ArtifactItem => Boolean(item) && typeof item === 'object') : [];
}

function routeLabel(item: ArtifactItem): string {
  const role = text(item.role);
  if (role === 'current') {
    return '현재';
  }
  if (role === 'next') {
    return '다음';
  }
  return role || '추천';
}

export default function CourseChatArtifacts({
  artifacts,
  includeKinds,
  disableLinks = false,
}: {
  artifacts: Array<Record<string, unknown>>;
  includeKinds?: string[];
  disableLinks?: boolean;
}) {
  if (!artifacts.length) {
    return null;
  }
  const allowedKinds = includeKinds ? new Set(includeKinds) : null;

  return (
    <div className="course-chat-artifacts">
      {artifacts.map((artifact, artifactIndex) => {
        const kind = text(artifact.kind);
        if (allowedKinds && !allowedKinds.has(kind)) {
          return null;
        }
        if (kind === 'course_guided_tour') {
          return (
            <section key={`chat-artifact-${artifactIndex}`} className="course-chat-artifact">
              <strong>{text(artifact.title) || 'Guided Tour'}</strong>
              <div className="course-chat-artifact-grid">
                {itemsOf(artifact).map((item, itemIndex) => {
                  const viewerPath = text(item.viewer_path);
                  const body = (
                    <>
                      <span>{routeLabel(item)}</span>
                      <strong>{publicText(item.question) || publicText(item.label) || publicText(item.title)}</strong>
                      <p>{publicText(item.label) || publicText(item.title)}</p>
                      <small>{publicText(item.reason)}</small>
                    </>
                  );
                  return viewerPath && !disableLinks ? (
                    <Link key={`route-${itemIndex}`} to={viewerPath} className="course-chat-artifact-card route">
                      {body}
                    </Link>
                  ) : (
                    <article key={`route-${itemIndex}`} className="course-chat-artifact-card route">
                      {body}
                    </article>
                  );
                })}
              </div>
            </section>
          );
        }

        if (kind === 'official_check') {
          return (
            <section key={`chat-artifact-${artifactIndex}`} className="course-chat-artifact">
              <strong>{text(artifact.title) || 'Official Check'}</strong>
              <p>{text(artifact.summary)}</p>
              <div className="course-chat-artifact-grid">
                {itemsOf(artifact).map((item, itemIndex) => (
                  <article key={`official-${itemIndex}`} className="course-chat-artifact-card official">
                    <span>공식문서</span>
                    <strong>{publicText(item.title) || publicText(item.book_slug)}</strong>
                    <p>{publicText(item.section_title) || publicText(item.section_id)}</p>
                    {text(item.match_reason) ? <small>{publicText(item.match_reason)}</small> : null}
                  </article>
                ))}
              </div>
            </section>
          );
        }

        if (kind === 'course_image_evidence') {
          return (
            <section key={`chat-artifact-${artifactIndex}`} className="course-chat-artifact">
              <strong>참고 이미지</strong>
              <div className="course-chat-artifact-grid">
                {itemsOf(artifact).slice(0, 3).map((item, itemIndex) => {
                  const viewerPath = text(item.viewer_path);
                  const assetPath = text(item.asset_path);
                  const body = (
                    <>
                      {assetPath ? <img src={buildCourseAssetUrl(assetPath)} alt={text(item.summary) || text(item.asset_id) || 'Course evidence'} /> : null}
                      <p>{publicText(item.summary)}</p>
                      <small>
                        Slide {text(item.slide_no)}
                        {text(item.state_signal) ? ` / ${text(item.state_signal)}` : ''}
                      </small>
                    </>
                  );
                  return viewerPath && !disableLinks ? (
                    <Link key={`image-${itemIndex}`} to={viewerPath} className="course-chat-artifact-card image">
                      {body}
                    </Link>
                  ) : (
                    <article key={`image-${itemIndex}`} className="course-chat-artifact-card image">
                      {body}
                    </article>
                  );
                })}
              </div>
            </section>
          );
        }

        return null;
      })}
    </div>
  );
}
