import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import './CoursePages.css';
import { ROUTES } from '../app/routes';
import { buildCourseAssetUrl, emptyCourseChatResponse, loadCourseChunk, loadCourseStage, sendCourseChatStream, type CourseChatResponse, type CourseChunkPayload, type CourseImageAttachment, type CourseStagePayload } from '../lib/courseApi';
import CourseChatWorkspaceAnswer from './CourseChatWorkspaceAnswer';

function shortText(value: unknown, maxLength = 420): string {
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

function attachmentTitle(attachment: CourseImageAttachment): string {
  return String(attachment.instructional_role || attachment.role || attachment.kind || 'image');
}

export default function CourseChunkPage() {
  const { chunkId = '' } = useParams();
  const [payload, setPayload] = useState<CourseChunkPayload | null>(null);
  const [stagePayload, setStagePayload] = useState<CourseStagePayload | null>(null);
  const [error, setError] = useState('');
  const [chatDraft, setChatDraft] = useState('');
  const [chatResponse, setChatResponse] = useState<CourseChatResponse | null>(null);
  const [chatLoading, setChatLoading] = useState(false);

  useEffect(() => {
    if (!chunkId) {
      return;
    }
    void loadCourseChunk(chunkId).then(setPayload).catch((caught) => {
      setError(caught instanceof Error ? caught.message : 'Failed to load chunk detail');
    });
  }, [chunkId]);

  useEffect(() => {
    if (!payload?.stage_id) {
      return;
    }
    void loadCourseStage(payload.stage_id).then(setStagePayload).catch(() => undefined);
  }, [payload?.stage_id]);

  const routeBadge = useMemo(() => {
    if (!payload || !stagePayload?.learning_route) {
      return '';
    }
    if ((stagePayload.learning_route.start_here ?? []).includes(payload.chunk_id)) {
      return 'Start Here';
    }
    if ((stagePayload.learning_route.then_open ?? []).includes(payload.chunk_id)) {
      return 'Then Open';
    }
    return '';
  }, [payload, stagePayload]);
  const atlasRefs = payload?.tour_stop?.atlas_expand_refs;
  const atlasRefCount = (atlasRefs?.child_chunk_ids?.length ?? 0) + (atlasRefs?.asset_ids?.length ?? 0) + (atlasRefs?.zone_ids?.length ?? 0);
  const sortedAttachments = useMemo(() => sortAttachments(payload?.image_attachments ?? []), [payload?.image_attachments]);
  const evidenceCards = useMemo(
    () => sortedAttachments.filter((attachment) => String(attachment.asset_path || '').trim()).slice(0, 6),
    [sortedAttachments],
  );
  const visibleAttachments = sortedAttachments.filter((attachment) => attachment.is_default_visible !== false);
  const overflowAttachments = sortedAttachments.filter((attachment) => attachment.is_default_visible === false);

  async function handleAskChunk() {
    const message = chatDraft.trim();
    if (!message || !payload) {
      return;
    }
    await runChunkQuestion(message, true);
  }

  async function runChunkQuestion(message: string, useChunkAnchor = false) {
    if (!message.trim() || !payload) {
      return;
    }
    setChatDraft(message);
    setChatLoading(true);
    let streamedAnswer = '';
    setChatResponse(emptyCourseChatResponse(''));
    try {
      const result = await sendCourseChatStream(
        { message, stage_id: payload.stage_id, chunk_ids: useChunkAnchor ? [payload.chunk_id] : undefined },
        (event) => {
          if (event.type === 'answer_delta') {
            streamedAnswer += event.delta;
            setChatResponse(emptyCourseChatResponse(streamedAnswer));
          }
        },
      );
      setChatResponse(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Failed to ask course chat');
    } finally {
      setChatLoading(false);
    }
  }

  return (
    <div className="course-page">
      <div className="course-shell">
        <header className="course-header">
          <h1>{payload?.native_id || chunkId}</h1>
          <p>{payload?.title || 'Chunk detail'}</p>
          {routeBadge ? <span className="course-chunk-route-badge">{routeBadge}</span> : null}
          {payload?.review_status ? <span className={`course-review-badge ${payload.review_status}`}>{payload.review_status}</span> : null}
        </header>

        <div className="course-inline-links">
          <Link to={ROUTES.courseHome}>Back to timeline</Link>
          {payload ? <Link to={ROUTES.courseStage(payload.stage_id)}>Back to stage</Link> : null}
        </div>

        {error ? <div className="course-panel course-detail">{error}</div> : null}

        {payload ? (
          <>
            {payload.tour_stop ? (
              <section className="course-panel course-detail course-tour-stop-panel">
                <div>
                  <span className="course-route-kicker">Guided Tour</span>
                  <strong>{payload.tour_stop.stage_title || payload.stage_id}</strong>
                  <p className="course-copy">
                    Stop {payload.tour_stop.stop_order} / {payload.tour_stop.total_stops}
                    {payload.tour_stop.route_role !== 'standard' ? ` · ${payload.tour_stop.route_role.replace('_', ' ')}` : ''}
                  </p>
                </div>
                <div className="course-tour-actions">
                  <button type="button" onClick={() => { void runChunkQuestion(`${payload.title} 흐름을 어떤 순서로 이해하면 돼?`, true); }} disabled={chatLoading}>
                    Ask current step
                  </button>
                  {payload.tour_stop.previous_chunk_id ? (
                    <Link to={ROUTES.courseChunk(payload.tour_stop.previous_chunk_id)}>Previous Stop</Link>
                  ) : (
                    <span className="course-muted">First stop</span>
                  )}
                  {payload.tour_stop.next_chunk_id ? (
                    <>
                      <button type="button" onClick={() => { void runChunkQuestion(`${payload.title} 다음에는 무엇을 확인하면 돼?`); }} disabled={chatLoading}>
                        Ask next step
                      </button>
                      <Link to={ROUTES.courseChunk(payload.tour_stop.next_chunk_id)}>Next Stop</Link>
                    </>
                  ) : (
                    <span className="course-muted">Last stop</span>
                  )}
                </div>
              </section>
            ) : null}

            <div className="course-split">
              <section className="course-panel course-detail">
                <strong>Structured Content</strong>
                {payload.review_notes?.length ? (
                  <div className="course-review-notes">
                    {payload.review_notes.map((note) => (
                      <span key={note} className="course-review-note">{note}</span>
                    ))}
                  </div>
                ) : null}
                <div className="course-structured-grid">
                  {Object.entries(payload.structured ?? {}).map(([key, value]) => (
                    <article key={key} className="course-structured-card">
                      <strong>{key}</strong>
                      <p>{String(value || '').trim() || 'No extracted content'}</p>
                    </article>
                  ))}
                </div>
                <pre>{payload.body_md}</pre>
              </section>

              <section className="course-panel course-detail">
                <strong>Official Check</strong>
                {(payload.related_official_docs ?? []).length ? (
                  <p className="course-copy">이 stop은 공식문서 확인 자료가 연결되어 있습니다. 사업 산출물을 먼저 보고, 아래 공식문서로 제품 기준을 대조합니다.</p>
                ) : (
                  <p className="course-copy">이 stop에는 신뢰 기준을 넘긴 공식문서 매핑이 없습니다. 원본 산출물과 슬라이드 근거를 우선 확인합니다.</p>
                )}
                <div className="course-source-list course-source-list-stack">
                  {(payload.related_official_docs ?? []).map((doc, index) => (
                    <div key={`official-${index}`} className="course-source-pill official_doc">
                      <strong>{String(doc.title || doc.book_slug || 'Official doc')}</strong>
                      <span>{String(doc.section_title || doc.section_id || '')}</span>
                      {doc.match_reason ? <span>{String(doc.match_reason)}</span> : null}
                      <span>{String(doc.snippet || '').slice(0, 180)}</span>
                    </div>
                  ))}
                </div>

                <strong>Atlas Expand</strong>
                <div className="course-atlas-box">
                  <span>{atlasRefCount} linked refs</span>
                  <span>{atlasRefs?.child_chunk_ids?.length ?? 0} child chunks</span>
                  <span>{atlasRefs?.asset_ids?.length ?? 0} assets</span>
                  <span>{atlasRefs?.zone_ids?.length ?? 0} zones</span>
                </div>
                <div className="course-inline-links course-atlas-action-row">
                  <Link to={ROUTES.courseAtlas(payload.chunk_id)}>Open Atlas Canvas</Link>
                </div>

                <strong>Image Attachments</strong>
                <div className="course-attachment-list">
                  {visibleAttachments.length === 0 ? (
                    <p className="course-muted">No default-visible image attachments. Use Atlas Canvas or review all assets before approving this chunk.</p>
                  ) : null}
                  {visibleAttachments.map((attachment, index) => (
                    <article key={`attachment-${index}`} className="course-attachment-card">
                      <div className="course-attachment-head">
                        <strong>{attachmentTitle(attachment)}</strong>
                        <span>Slide {String(attachment.slide_no || '')}</span>
                      </div>
                      <div className="course-attachment-meta">
                        {attachment.asset_id ? <span>{attachment.asset_id}</span> : null}
                        {attachment.zone_id ? <span>zone {attachment.zone_id}</span> : <span className="course-muted">zone link missing</span>}
                      </div>
                      <div className="course-attachment-badges">
                        {attachmentBadges(attachment).map((badge) => (
                          <span key={badge}>{badge}</span>
                        ))}
                      </div>
                      {attachment.asset_path ? (
                        <img className="course-attachment-image" src={buildCourseAssetUrl(attachment.asset_path)} alt={attachment.visual_summary || attachment.asset_id || 'Course evidence'} />
                      ) : null}
                      {attachment.visual_summary ? (
                        <p>{shortText(attachment.visual_summary)}</p>
                      ) : (
                        <p className="course-muted">No visual summary. Review the slide image and OCR before approving this asset.</p>
                      )}
                      {attachment.ocr_text ? (
                        <details className="course-attachment-ocr">
                          <summary>OCR text</summary>
                          <pre>{shortText(attachment.ocr_text, 1200)}</pre>
                        </details>
                      ) : null}
                      <span>{String(attachment.asset_path || '')}</span>
                    </article>
                  ))}
                </div>
                {overflowAttachments.length ? (
                  <details className="course-attachment-more">
                    <summary>{overflowAttachments.length} more lower-ranked or duplicate attachments</summary>
                    <div className="course-attachment-list">
                      {overflowAttachments.map((attachment, index) => (
                        <article key={`overflow-attachment-${index}`} className="course-attachment-card secondary">
                          <div className="course-attachment-head">
                            <strong>{attachmentTitle(attachment)}</strong>
                            <span>Slide {String(attachment.slide_no || '')}</span>
                          </div>
                          <div className="course-attachment-meta">
                            {attachment.asset_id ? <span>{attachment.asset_id}</span> : null}
                            {attachment.duplicate_of_asset_id ? <span>duplicate of {attachment.duplicate_of_asset_id}</span> : null}
                            {attachment.zone_id ? <span>zone {attachment.zone_id}</span> : <span className="course-muted">zone link missing</span>}
                          </div>
                          <div className="course-attachment-badges">
                            {attachmentBadges(attachment).map((badge) => (
                              <span key={badge}>{badge}</span>
                            ))}
                          </div>
                          {attachment.asset_path ? (
                            <img className="course-attachment-image" src={buildCourseAssetUrl(attachment.asset_path)} alt={attachment.visual_summary || attachment.asset_id || 'Course evidence'} />
                          ) : null}
                          <p>{shortText(attachment.visual_summary || attachment.caption_text || attachment.ocr_text || 'No visual text')}</p>
                          <span>{String(attachment.asset_path || '')}</span>
                        </article>
                      ))}
                    </div>
                  </details>
                ) : null}

                {payload.child_chunk_ids.length > 0 ? (
                  <>
                    <strong>Child Chunks</strong>
                    <div className="course-child-list">
                      {payload.child_chunk_ids.map((childId) => (
                        <Link key={childId} to={ROUTES.courseChunk(childId)} className="course-child-card">
                          <strong>{childId}</strong>
                          <span>Open detail</span>
                        </Link>
                      ))}
                    </div>
                  </>
                ) : null}
              </section>
            </div>

            <section className="course-panel course-detail">
              <strong>Evidence Images</strong>
              <div className="course-slide-grid">
                {evidenceCards.map((attachment, index) => {
                  const slideNo = Number(attachment.slide_no || 0);
                  return (
                    <article key={`evidence-${attachment.asset_id || index}`} className="course-slide-card">
                      <img src={buildCourseAssetUrl(String(attachment.asset_path || ''))} alt={attachment.visual_summary || `Slide ${slideNo}`} />
                      <span>{slideNo ? `Slide ${slideNo}` : 'Evidence'}</span>
                    </article>
                  );
                })}
              </div>
            </section>

            <section className="course-panel course-detail">
              <strong>Ask This Chunk</strong>
              <div className="course-chat-box">
                <textarea value={chatDraft} onChange={(event) => setChatDraft(event.target.value)} placeholder="이 설계ID 또는 테스트ID에 대해 질문하세요." />
                <button type="button" onClick={() => { void handleAskChunk(); }} disabled={chatLoading}>
                  {chatLoading ? 'Running...' : 'Ask'}
                </button>
              </div>
              {chatResponse ? (
                <div className="course-chat-answer">
                  <CourseChatWorkspaceAnswer response={chatResponse} onSuggestedQuery={(suggestedQuery) => { void runChunkQuestion(suggestedQuery); }} />
                </div>
              ) : null}
            </section>
          </>
        ) : null}
      </div>
    </div>
  );
}
