import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import './CoursePages.css';
import { ROUTES } from '../app/routes';
import { buildCourseAssetUrl, buildCourseSlideUrl, loadCourseChunk, type CourseChunkPayload, type CourseImageAttachment } from '../lib/courseApi';

function shortText(value: unknown, maxLength = 260): string {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength).trim()}...`;
}

function sortAttachments(attachments: CourseImageAttachment[]): CourseImageAttachment[] {
  return [...attachments].sort((left, right) => {
    const leftVisible = left.is_default_visible ? 0 : 1;
    const rightVisible = right.is_default_visible ? 0 : 1;
    if (leftVisible !== rightVisible) {
      return leftVisible - rightVisible;
    }
    const leftDefault = left.default_visible_order || 999;
    const rightDefault = right.default_visible_order || 999;
    if (leftDefault !== rightDefault) {
      return leftDefault - rightDefault;
    }
    return (left.image_rank_order || 999) - (right.image_rank_order || 999);
  });
}

function attachmentBadges(attachment: CourseImageAttachment): string[] {
  return [
    attachment.instructional_role,
    attachment.quality_label,
    attachment.state_signal,
    typeof attachment.evidence_strength === 'number' ? `evidence ${attachment.evidence_strength.toFixed(2)}` : '',
  ].filter((value): value is string => Boolean(value));
}

export default function CourseAtlasPage() {
  const { chunkId = '' } = useParams();
  const [payload, setPayload] = useState<CourseChunkPayload | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!chunkId) {
      return;
    }
    void loadCourseChunk(chunkId).then(setPayload).catch((caught) => {
      setError(caught instanceof Error ? caught.message : 'Failed to load course atlas');
    });
  }, [chunkId]);

  const atlasRefs = payload?.tour_stop?.atlas_expand_refs;
  const childIds = atlasRefs?.child_chunk_ids ?? payload?.child_chunk_ids ?? [];
  const assetIds = atlasRefs?.asset_ids ?? [];
  const zoneIds = atlasRefs?.zone_ids ?? [];
  const slideCards = useMemo(() => (payload?.slide_refs ?? []).slice(0, 4), [payload]);
  const relatedDocs = payload?.related_official_docs ?? [];
  const attachments = useMemo(() => sortAttachments(payload?.image_attachments ?? []), [payload?.image_attachments]);

  return (
    <div className="course-page">
      <div className="course-shell">
        <header className="course-header">
          <h1>Atlas Canvas</h1>
          <p>{payload ? `${payload.native_id} · ${payload.title}` : 'Course relationship canvas'}</p>
        </header>

        <div className="course-inline-links">
          <Link to={ROUTES.courseHome}>Back to timeline</Link>
          {payload ? <Link to={ROUTES.courseStage(payload.stage_id)}>Back to stage</Link> : null}
          {payload ? <Link to={ROUTES.courseChunk(payload.chunk_id)}>Back to stop</Link> : null}
        </div>

        {error ? <div className="course-panel course-detail">{error}</div> : null}

        {payload ? (
          <>
            <section className="course-panel course-detail course-atlas-hero">
              <div>
                <span className="course-route-kicker">Document + Relation + Figure</span>
                <strong>{payload.title}</strong>
                <p className="course-copy">
                  이 화면은 Guided Tour의 현재 stop을 중심으로 원본 슬라이드, 이미지 asset, semantic zone, child chunk,
                  공식문서 참조를 한 번에 펼칩니다.
                </p>
              </div>
              <div className="course-atlas-metrics">
                <span>{childIds.length} child chunks</span>
                <span>{assetIds.length} assets</span>
                <span>{zoneIds.length} zones</span>
                <span>{relatedDocs.length} official docs</span>
              </div>
            </section>

            <section className="course-atlas-canvas">
              <article className="course-atlas-node course-atlas-node-primary">
                <span>Current Stop</span>
                <strong>{payload.native_id}</strong>
                <p>{payload.title}</p>
                {payload.tour_stop ? (
                  <small>Stop {payload.tour_stop.stop_order} / {payload.tour_stop.total_stops}</small>
                ) : null}
              </article>

              <div className="course-atlas-node-grid">
                <article className="course-atlas-node">
                  <span>Tour Route</span>
                  {payload.tour_stop?.previous_chunk_id ? (
                    <Link to={ROUTES.courseChunk(payload.tour_stop.previous_chunk_id)}>Previous Stop</Link>
                  ) : (
                    <small>First stop</small>
                  )}
                  {payload.tour_stop?.next_chunk_id ? (
                    <Link to={ROUTES.courseChunk(payload.tour_stop.next_chunk_id)}>Next Stop</Link>
                  ) : (
                    <small>Last stop</small>
                  )}
                </article>

                <article className="course-atlas-node">
                  <span>Official Check</span>
                  {relatedDocs.length ? (
                    relatedDocs.slice(0, 4).map((doc, index) => (
                      <small key={`doc-${index}`}>{String(doc.title || doc.book_slug || doc.section_id || 'Official doc')}</small>
                    ))
                  ) : (
                    <small>No trusted official mapping</small>
                  )}
                </article>

                <article className="course-atlas-node">
                  <span>Child Chunks</span>
                  {childIds.length ? (
                    childIds.slice(0, 5).map((id) => (
                      <Link key={id} to={ROUTES.courseChunk(id)}>{id}</Link>
                    ))
                  ) : (
                    <small>No child chunks</small>
                  )}
                </article>

                <article className="course-atlas-node">
                  <span>Semantic Zones</span>
                  {zoneIds.length ? zoneIds.slice(0, 8).map((id) => <small key={id}>{id}</small>) : <small>No linked zones</small>}
                </article>
              </div>
            </section>

            <section className="course-split">
              <div className="course-panel course-detail">
                <strong>Figure Strip</strong>
                <div className="course-attachment-list">
                  {attachments.map((attachment, index) => (
                    <article key={`${attachment.asset_id || index}`} className="course-attachment-card">
                      <div className="course-attachment-head">
                        <strong>{attachment.instructional_role || attachment.role || attachment.kind || 'image'}</strong>
                        <span>Slide {attachment.slide_no || ''}</span>
                      </div>
                      <div className="course-attachment-meta">
                        {attachment.asset_id ? <span>{attachment.asset_id}</span> : null}
                        {attachment.zone_id ? <span>zone {attachment.zone_id}</span> : null}
                        {attachment.duplicate_of_asset_id ? <span>duplicate of {attachment.duplicate_of_asset_id}</span> : null}
                      </div>
                      <div className="course-attachment-badges">
                        {attachmentBadges(attachment).map((badge) => (
                          <span key={badge}>{badge}</span>
                        ))}
                      </div>
                      {attachment.asset_path ? (
                        <img className="course-attachment-image" src={buildCourseAssetUrl(attachment.asset_path)} alt={attachment.visual_summary || attachment.asset_id || 'Course evidence'} />
                      ) : null}
                      <p>{shortText(attachment.visual_summary)}</p>
                      <span>{attachment.asset_path || ''}</span>
                    </article>
                  ))}
                </div>
              </div>

              <div className="course-panel course-detail">
                <strong>Original Slide Context</strong>
                <div className="course-slide-grid">
                  {slideCards.map((slideRef, index) => {
                    const slideNo = Number(slideRef.slide_no || 0);
                    return (
                      <article key={`atlas-slide-${slideNo}-${index}`} className="course-slide-card">
                        <img src={buildCourseSlideUrl(payload.chunk_id, slideNo)} alt={`Slide ${slideNo}`} />
                        <span>Slide {slideNo}</span>
                      </article>
                    );
                  })}
                </div>
              </div>
            </section>
          </>
        ) : null}
      </div>
    </div>
  );
}
