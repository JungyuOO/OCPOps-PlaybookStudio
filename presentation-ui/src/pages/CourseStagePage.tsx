import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import './CoursePages.css';
import { ROUTES } from '../app/routes';
import {
  loadCourseManifest,
  loadCourseStage,
  emptyCourseChatResponse,
  sendCourseChatStream,
  type CourseChatResponse,
  type CourseChunkRef,
  type CourseGuidedCard,
  type CourseManifest,
  type CourseStagePayload,
} from '../lib/courseApi';
import CourseChatWorkspaceAnswer from './CourseChatWorkspaceAnswer';

type GroupedChunk = {
  nativeId: string;
  variants: CourseChunkRef[];
  officialRefCount: number;
  slideCount: number;
  primaryTitle: string;
};

type GuidedQuestionContext = {
  chunkId?: string;
  guideId?: string;
  stageId?: string;
  stepId?: string;
};

function groupChunksByNativeId(chunks: CourseChunkRef[]): GroupedChunk[] {
  const groups = new Map<string, CourseChunkRef[]>();
  for (const chunk of chunks) {
    const key = chunk.native_id || chunk.chunk_id;
    const rows = groups.get(key) ?? [];
    rows.push(chunk);
    groups.set(key, rows);
  }
  return [...groups.entries()]
    .map(([nativeId, variants]) => ({
      nativeId,
      variants,
      officialRefCount: Math.max(...variants.map((item) => item.related_official_docs.length)),
      slideCount: variants.reduce((sum, item) => sum + item.slide_count, 0),
      primaryTitle: variants[0]?.title || nativeId,
    }))
    .sort((left, right) => {
      if (right.officialRefCount !== left.officialRefCount) {
        return right.officialRefCount - left.officialRefCount;
      }
      return left.nativeId.localeCompare(right.nativeId);
    });
}

const STAGE_COPY: Record<string, string> = {
  architecture: '설계 산출물을 운영 관점의 학습 단계로 묶어 전체 구조와 핵심 서비스 흐름을 먼저 이해합니다.',
  unit_test: '단위 테스트 케이스를 따라가며 검증 방법, 기대 결과, 화면 증적을 학습합니다.',
  integration_test: 'CI/CD 통합 시나리오를 파이프라인 실행, 배포, 서비스 접근 확인 순서로 학습합니다.',
  perf_test: '성능 목표, 테스트 조건, 병목, 개선 포인트를 운영 점검 순서로 확인합니다.',
  completion: '완료보고서를 사업 범위, 아키텍처 결과, 전환 결과, 테스트 결과 순서로 정리합니다.',
};

function pickRouteChunks(chunks: CourseChunkRef[], ids: string[]): CourseChunkRef[] {
  const byId = new Map(chunks.map((chunk) => [chunk.chunk_id, chunk]));
  return ids.map((id) => byId.get(id)).filter((chunk): chunk is CourseChunkRef => Boolean(chunk));
}

function cleanCardLabel(value: string): string {
  return value
    .replace(/\bKMSC\s+COCP\s+RTER\s+\d+\s*/gi, '')
    .replace(/\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b/g, '')
    .replace(/\b(?:KMSC|COCP|RTER|PLAN|RESULT|FRONT)\b/gi, '')
    .replace(/\bCH-\d+\b/gi, '')
    .replace(/\s+/g, ' ')
    .replace(/^[-:_\s]+|[-:_\s]+$/g, '')
    || '운영 학습 단계';
}

function guidedCardFromChunk(chunk: CourseChunkRef, role: CourseGuidedCard['role']): CourseGuidedCard {
  const label = chunk.beginner_label || cleanCardLabel(chunk.title);
  const question = role === 'then_open'
    ? (chunk.next_question || `${label} 다음에는 무엇을 확인하면 돼?`)
    : role === 'official_check'
      ? `${label}를 공식문서 기준과 실운영 기준으로 같이 설명해줘`
      : (chunk.beginner_question || `${label} 흐름을 어떤 순서로 이해하면 돼?`);
  return {
    role,
    chunk_id: chunk.chunk_id,
    stage_id: '',
    label,
    question,
    viewer_path: ROUTES.courseChunk(chunk.chunk_id),
    atlas_path: ROUTES.courseAtlas(chunk.chunk_id),
    slide_count: chunk.slide_count,
    official_ref_count: chunk.related_official_docs.length,
    source: {
      chunk_id: chunk.chunk_id,
      native_id: chunk.native_id,
      hidden_doc_anchor: true,
    },
  };
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function findSuggestedQuestionContext(response: CourseChatResponse | null, query: string): GuidedQuestionContext | undefined {
  const normalizedQuery = query.trim();
  if (!normalizedQuery || !response?.artifacts?.length) {
    return undefined;
  }

  for (const artifact of response.artifacts) {
    if (artifact.kind !== 'course_guided_tour' || !Array.isArray(artifact.items)) {
      continue;
    }
    const items = artifact.items as Array<Record<string, unknown>>;
    const match = items.find((item) => stringValue(item.question) === normalizedQuery);
    if (!match) {
      continue;
    }
    return {
      chunkId: stringValue(match.chunk_id) || undefined,
      guideId: stringValue(match.guide_id) || undefined,
      stageId: stringValue(match.stage_id) || undefined,
      stepId: stringValue(match.step_id) || undefined,
    };
  }

  return undefined;
}

export default function CourseStagePage() {
  const { stageId = '' } = useParams();
  const [payload, setPayload] = useState<CourseStagePayload | null>(null);
  const [manifest, setManifest] = useState<CourseManifest | null>(null);
  const [error, setError] = useState('');
  const [chatDraft, setChatDraft] = useState('');
  const [chatResponse, setChatResponse] = useState<CourseChatResponse | null>(null);
  const [chatLoading, setChatLoading] = useState(false);
  const [filterText, setFilterText] = useState('');
  const [visibleGroupCount, setVisibleGroupCount] = useState(18);

  useEffect(() => {
    if (!stageId) {
      return;
    }
    setVisibleGroupCount(18);
    void loadCourseStage(stageId).then(setPayload).catch((caught) => {
      setError(caught instanceof Error ? caught.message : 'Failed to load course stage');
    });
    void loadCourseManifest().then(setManifest).catch(() => undefined);
  }, [stageId]);

  const groupedChunks = useMemo(() => groupChunksByNativeId(payload?.chunks ?? []), [payload]);

  const filteredGroups = useMemo(() => {
    const normalizedFilter = filterText.trim().toLowerCase();
    if (!normalizedFilter) {
      return groupedChunks;
    }
    return groupedChunks.filter((group) => {
      const haystack = `${group.nativeId} ${group.primaryTitle} ${group.variants.map((item) => `${item.title} ${item.variant || ''}`).join(' ')}`.toLowerCase();
      return haystack.includes(normalizedFilter);
    });
  }, [filterText, groupedChunks]);

  const visibleGroups = useMemo(() => filteredGroups.slice(0, visibleGroupCount), [filteredGroups, visibleGroupCount]);
  const featuredGroups = useMemo(() => filteredGroups.slice(0, 3), [filteredGroups]);

  const totalVariantCount = useMemo(
    () => groupedChunks.reduce((sum, group) => sum + group.variants.length, 0),
    [groupedChunks],
  );
  const totalOfficialRefCount = useMemo(
    () => groupedChunks.reduce((sum, group) => sum + group.officialRefCount, 0),
    [groupedChunks],
  );

  const stageOrder = manifest?.stages ?? [];
  const activeIndex = stageOrder.findIndex((stage) => stage.stage_id === stageId);
  const previousStage = activeIndex > 0 ? stageOrder[activeIndex - 1] : null;
  const nextStage = activeIndex >= 0 && activeIndex < stageOrder.length - 1 ? stageOrder[activeIndex + 1] : null;

  const routeStart = useMemo(
    () => pickRouteChunks(payload?.chunks ?? [], payload?.learning_route?.start_here ?? []),
    [payload],
  );
  const routeThenOpen = useMemo(
    () => pickRouteChunks(payload?.chunks ?? [], payload?.learning_route?.then_open ?? []),
    [payload],
  );
  const guidedStartCards = useMemo(
    () => (payload?.guided_cards?.start_here?.length
      ? payload.guided_cards.start_here
      : routeStart.map((chunk) => guidedCardFromChunk(chunk, 'start_here'))),
    [payload, routeStart],
  );
  const guidedThenCards = useMemo(
    () => (payload?.guided_cards?.then_open?.length
      ? payload.guided_cards.then_open
      : routeThenOpen.map((chunk) => guidedCardFromChunk(chunk, 'then_open'))),
    [payload, routeThenOpen],
  );
  const officialCheckChunks = useMemo(
    () => filteredGroups
      .flatMap((group) => group.variants)
      .filter((chunk) => chunk.related_official_docs.length > 0)
      .slice(0, 4),
    [filteredGroups],
  );
  const guidedOfficialCards = useMemo(
    () => (payload?.guided_cards?.official_check?.length
      ? payload.guided_cards.official_check
      : officialCheckChunks.map((chunk) => guidedCardFromChunk(chunk, 'official_check'))),
    [officialCheckChunks, payload],
  );
  const stageOfficialRefs = useMemo(() => payload?.official_route_refs ?? [], [payload]);

  async function handleAskStage() {
    const message = chatDraft.trim();
    if (!message || !stageId) {
      return;
    }
    await runGuidedQuestion(message);
  }

  async function runGuidedQuestion(message: string, options?: GuidedQuestionContext) {
    const targetStageId = options?.stageId || stageId;
    if (!message.trim() || !targetStageId) {
      return;
    }
    setChatDraft(message);
    setChatLoading(true);
    let streamedAnswer = '';
    setChatResponse(emptyCourseChatResponse(''));
    try {
      const result = await sendCourseChatStream(
        {
          message,
          stage_id: targetStageId,
          guide_id: options?.guideId,
          step_id: options?.stepId,
          chunk_ids: options?.guideId ? undefined : options?.chunkId ? [options.chunkId] : undefined,
        },
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
          <h1>{payload?.title || stageId}</h1>
          <p>{STAGE_COPY[stageId] || '이 단계는 실운영 산출물과 공식문서를 함께 읽는 운영 학습 구간입니다.'}</p>
        </header>

        <div className="course-inline-links">
          <Link to={ROUTES.courseHome}>Back to timeline</Link>
          {previousStage ? <Link to={ROUTES.courseStage(previousStage.stage_id)}>Previous stage</Link> : null}
          {nextStage ? <Link to={ROUTES.courseStage(nextStage.stage_id)}>Next stage</Link> : null}
        </div>

        {error ? <div className="course-panel course-detail">{error}</div> : null}

        <section className="course-panel course-detail course-stage-hero">
          <strong>Stage Overview</strong>
          <p className="course-copy">
            이 단계는 PBS 추천 카드 방식으로 먼저 볼 운영 학습 질문, 이어서 볼 후속 질문, 공식문서 확인 지점을 순서대로 제시합니다.
            카드를 누르면 바로 답변과 근거, 다음 단계가 이어집니다.
          </p>
          <div className="course-stat-grid">
            <article className="course-stat-card">
              <strong>{groupedChunks.length}</strong>
              <span>Groups</span>
            </article>
            <article className="course-stat-card">
              <strong>{totalVariantCount}</strong>
              <span>Variants</span>
            </article>
            <article className="course-stat-card">
              <strong>{totalOfficialRefCount}</strong>
              <span>Official refs</span>
            </article>
            <article className="course-stat-card">
              <strong>{payload?.review_summary?.approved ?? 0}</strong>
              <span>Approved</span>
            </article>
            <article className="course-stat-card">
              <strong>{payload?.review_summary?.needs_review ?? 0}</strong>
              <span>Needs review</span>
            </article>
          </div>
        </section>

        {(guidedStartCards.length > 0 || guidedThenCards.length > 0 || guidedOfficialCards.length > 0) ? (
          <section className="course-guided-stack">
            <div className="course-panel course-detail course-guided-route">
              <div className="course-guided-route-head">
                <div>
                  <span className="course-route-kicker">Guided Tour</span>
                  <strong>추천 카드 순서대로 따라가면 됩니다</strong>
                  <p className="course-copy">{payload?.learning_route?.why_this_order || '운영 학습 흐름에 맞춰 먼저 볼 질문과 후속 질문을 제공합니다.'}</p>
                </div>
              </div>
              <div className="course-recommendation-band">
                {guidedStartCards.length > 0 ? (
                  <div className="course-guided-lane">
                    <div className="course-guided-lane-label">Start Here</div>
                    {guidedStartCards.map((card, index) => (
                      <article key={`route-start-${card.step_id || card.chunk_id}`} className="course-recommendation-card primary">
                        <span className="course-guided-kicker">Step {index + 1}</span>
                        <strong>{card.question}</strong>
                        <p>{card.label}</p>
                        <span>{card.slide_count} slides / {card.official_ref_count} official refs</span>
                        <div className="course-card-actions">
                          <button
                            type="button"
                            onClick={() => {
                              void runGuidedQuestion(card.question, { chunkId: card.chunk_id, guideId: card.guide_id, stepId: card.step_id });
                            }}
                            disabled={chatLoading}
                          >
                            Ask
                          </button>
                          {card.chunk_id ? <Link to={ROUTES.courseChunk(card.chunk_id)}>Open detail</Link> : null}
                          {card.chunk_id ? <Link to={ROUTES.courseAtlas(card.chunk_id)}>Atlas</Link> : null}
                        </div>
                      </article>
                    ))}
                  </div>
                ) : null}

                {guidedThenCards.length > 0 ? (
                  <div className="course-guided-lane">
                    <div className="course-guided-lane-label">Then Open</div>
                    {guidedThenCards.map((card, index) => (
                      <article key={`route-doc-${card.step_id || card.chunk_id}`} className="course-recommendation-card">
                        <span className="course-guided-kicker">Follow-up {index + 1}</span>
                        <strong>{card.question}</strong>
                        <p>{card.label}</p>
                        <span>{card.slide_count} slides / {card.official_ref_count} official refs</span>
                        <div className="course-card-actions">
                          <button
                            type="button"
                            onClick={() => {
                              void runGuidedQuestion(card.question, { chunkId: card.chunk_id, guideId: card.guide_id, stepId: card.step_id });
                            }}
                            disabled={chatLoading}
                          >
                            Ask
                          </button>
                          {card.chunk_id ? <Link to={ROUTES.courseChunk(card.chunk_id)}>Open detail</Link> : null}
                          {card.chunk_id ? <Link to={ROUTES.courseAtlas(card.chunk_id)}>Atlas</Link> : null}
                        </div>
                      </article>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>

            <section className="course-panel course-detail">
              <div className="course-guided-route-head">
                <div>
                  <span className="course-route-kicker">Official Check</span>
                  <strong>공식문서 기준으로 대조할 문서</strong>
                  <p className="course-copy">공식문서 참조가 연결된 산출물만 먼저 보여줍니다. 실운영 자료를 읽은 뒤 제품 기준을 확인할 때 사용합니다.</p>
                </div>
              </div>
              {guidedOfficialCards.length > 0 ? (
                <div className="course-official-card-grid">
                  {guidedOfficialCards.map((card) => (
                    <article key={`official-check-${card.step_id || card.chunk_id}`} className="course-official-check-card">
                      <strong>{card.question}</strong>
                      <span>{card.label}</span>
                      <span>{card.official_ref_count} official refs</span>
                      <div className="course-card-actions">
                        <button
                          type="button"
                          onClick={() => {
                            void runGuidedQuestion(card.question, { chunkId: card.chunk_id, guideId: card.guide_id, stepId: card.step_id });
                          }}
                          disabled={chatLoading}
                        >
                          Ask
                        </button>
                        {card.chunk_id ? <Link to={ROUTES.courseChunk(card.chunk_id)}>Open detail</Link> : null}
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <>
                  <p className="course-copy">청크 단위 공식문서 매핑이 확정되지 않았습니다. 이 단계 전체를 대조할 공식문서 route를 먼저 제공합니다.</p>
                  <div className="course-official-card-grid">
                    {stageOfficialRefs.map((doc, index) => (
                      <article key={`stage-official-${index}`} className="course-official-check-card">
                        <strong>{String(doc.title || doc.book_slug || 'Official doc')}</strong>
                        <span>{String(doc.section_title || doc.section_id || '')}</span>
                        <span>{String(doc.match_reason || '')}</span>
                      </article>
                    ))}
                  </div>
                </>
              )}
            </section>

            {nextStage ? (
              <section className="course-panel course-detail course-next-stage-panel">
                <div>
                  <span className="course-route-kicker">Next Stage</span>
                  <strong>{nextStage.title}</strong>
                  <p className="course-copy">이 단계의 핵심 카드를 확인한 뒤 다음 단계로 이어서 진행합니다.</p>
                </div>
                <Link to={ROUTES.courseStage(nextStage.stage_id)}>Open Next Stage</Link>
              </section>
            ) : null}
          </section>
        ) : null}

        <section className="course-feature-grid">
          {featuredGroups.map((group) => (
            <article key={`featured-${group.nativeId}`} className="course-panel course-feature-card">
              <span className="course-muted">Featured</span>
              <strong>{cleanCardLabel(group.primaryTitle)}</strong>
              <p>공식문서 참조가 많은 운영 학습 근거입니다.</p>
              <span>{group.variants.length} variants / {group.officialRefCount} official refs</span>
            </article>
          ))}
        </section>

        <section className="course-panel course-detail">
          <strong>Explore Groups</strong>
          <div className="course-stage-toolbar">
            <input
              value={filterText}
              onChange={(event) => setFilterText(event.target.value)}
              placeholder="설계 ID, 테스트 ID, 키워드로 필터"
            />
            <span className="course-muted">{filteredGroups.length} groups</span>
          </div>
        </section>

        <section className="course-group-list">
          {visibleGroups.map((group) => (
            <details key={group.nativeId} className="course-group-panel">
              <summary className="course-group-summary">
                <div>
                  <strong>{cleanCardLabel(group.primaryTitle)}</strong>
                  <span className="course-muted">{group.variants.length} variants / {group.slideCount} slides</span>
                </div>
                <span className="course-muted">{group.officialRefCount} official refs</span>
              </summary>
              <div className="course-list">
                {group.variants.slice(0, 6).map((chunk) => (
                  <Link key={chunk.chunk_id} to={ROUTES.courseChunk(chunk.chunk_id)} className="course-chunk-card">
                    {chunk.review_status ? (
                      <span className={`course-review-badge ${chunk.review_status}`}>{chunk.review_status}</span>
                    ) : null}
                    <strong>{chunk.title}</strong>
                    <span>{chunk.variant || 'base'}</span>
                    <span>{chunk.slide_count} slide refs / {chunk.related_official_docs.length} official refs</span>
                  </Link>
                ))}
                {group.variants.length > 6 ? (
                  <div className="course-group-more">
                    {group.variants.length - 6} more variants exist for this ID.
                  </div>
                ) : null}
              </div>
            </details>
          ))}
        </section>

        {visibleGroups.length < filteredGroups.length ? (
          <button type="button" className="course-load-more-btn" onClick={() => setVisibleGroupCount((current) => current + 18)}>
            Load more groups
          </button>
        ) : null}

        <section className="course-panel course-detail">
          <strong>Ask This Stage</strong>
          <div className="course-chat-box">
            <textarea value={chatDraft} onChange={(event) => setChatDraft(event.target.value)} placeholder="이 단계에서 궁금한 운영 흐름이나 검증 방법을 질문해 보세요" />
            <button type="button" onClick={() => { void handleAskStage(); }} disabled={chatLoading}>
              {chatLoading ? 'Running...' : 'Ask'}
            </button>
          </div>
          {chatResponse ? (
            <div className="course-chat-answer">
              <CourseChatWorkspaceAnswer
                response={chatResponse}
                onSuggestedQuery={(suggestedQuery) => {
                  void runGuidedQuestion(suggestedQuery, findSuggestedQuestionContext(chatResponse, suggestedQuery));
                }}
              />
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
