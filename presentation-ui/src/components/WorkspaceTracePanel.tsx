import { Fragment, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ClipboardCopy,
  Loader2,
  Minus,
  XCircle,
} from 'lucide-react';
import type { ChatResponse, ChatTraceEvent } from '../lib/runtimeApi';
import {
  type ScorecardItem,
  type Severity,
  type Verdict,
  deriveSeverity,
  deriveVerdict,
  evaluateScorecard,
  summarizeScorecard,
} from './scorecardEval';
import { deriveWorkspaceExplain } from './workspaceExplain';
import './WorkspaceTracePanel.css';

interface WorkspaceTracePanelProps {
  query: string;
  events: ChatTraceEvent[];
  result?: ChatResponse | null;
  isSending: boolean;
}

type ViewMode = 'explain' | 'overview' | 'forensic';

/**
 * Backend whitelist of step IDs we know how to render. Other steps still show
 * up in the Forensic events table — only the timeline filters by this set so
 * the overview surface stays curated.
 */
const TIMELINE_STEPS: ReadonlyArray<string> = [
  'request_received',
  'route_query',
  'normalize_query',
  'rewrite_query',
  'decompose_query',
  'bm25_search',
  'vector_search',
  'fusion',
  'rerank',
  'retrieval',
  'context_assembly',
  'grounding_guard',
  'prompt_build',
  'llm_runtime',
  'deterministic_answer',
  'citation_finalize',
  'pipeline_complete',
  'stream_error',
];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function formatMs(value: unknown, fallback = '–'): string {
  const num = asNumber(value);
  if (num === null) return fallback;
  if (num >= 1000) return `${(num / 1000).toFixed(2)}s`;
  if (num >= 100) return `${Math.round(num)}ms`;
  return `${num.toFixed(num < 10 ? 1 : 0)}ms`;
}

function formatScore(value: unknown, fallback = '–'): string {
  const num = asNumber(value);
  if (num === null) return fallback;
  return num.toFixed(3);
}

function shortSession(id: string | undefined): string {
  if (!id) return 'no-session';
  return id.length > 14 ? `${id.slice(0, 6)}…${id.slice(-4)}` : id;
}

interface DerivedStage {
  step: string;
  label: string;
  status: 'idle' | 'running' | 'done' | 'error';
  detail: string | null;
  durationMs: number | null;
  timestampMs: number | null;
  meta: Record<string, unknown>;
  ordinal: number;
}

interface ForensicHitRow {
  key: string;
  bookSlug: string;
  section: string;
  bm25Rank: number | null;
  vectorRank: number | null;
  hybridRank: number | null;
  rerankRank: number | null;
  bm25Score: number | null;
  vectorScore: number | null;
  fusedScore: number | null;
  survived: boolean;
}

/**
 * Collapse multiple events for the same step into a single stage entry.
 * Backend emits `running` then `done` for many steps; we keep the latest
 * status but accumulate the longest duration (`done` carries duration_ms).
 */
function collapseStages(events: ChatTraceEvent[]): DerivedStage[] {
  const byStep = new Map<string, DerivedStage>();
  events.forEach((event, index) => {
    if (!event.step) return;
    const existing = byStep.get(event.step);
    const status = ((): DerivedStage['status'] => {
      if (event.status === 'error') return 'error';
      if (event.status === 'done') return 'done';
      if (event.status === 'running') return 'running';
      return existing?.status ?? 'idle';
    })();
    const merged: DerivedStage = {
      step: event.step,
      label: event.label || existing?.label || event.step,
      status: existing?.status === 'error' ? 'error' : status,
      detail: event.detail ?? existing?.detail ?? null,
      durationMs: asNumber(event.duration_ms) ?? existing?.durationMs ?? null,
      timestampMs: asNumber(event.timestamp_ms) ?? existing?.timestampMs ?? null,
      meta: { ...(existing?.meta ?? {}), ...(event.meta ?? {}) },
      ordinal: existing?.ordinal ?? index,
    };
    byStep.set(event.step, merged);
  });
  return Array.from(byStep.values()).sort((a, b) => a.ordinal - b.ordinal);
}

function deriveForensicHitRows(retrievalTrace: Record<string, unknown>): ForensicHitRow[] {
  const stages = {
    bm25: asArray(retrievalTrace.bm25).map((hit) => asRecord(hit)),
    vector: asArray(retrievalTrace.vector).map((hit) => asRecord(hit)),
    hybrid: asArray(retrievalTrace.hybrid).map((hit) => asRecord(hit)),
    reranked: asArray(retrievalTrace.reranked).map((hit) => asRecord(hit)),
  };

  const rows = new Map<string, ForensicHitRow>();
  const ensureRow = (hit: Record<string, unknown>): ForensicHitRow => {
    const key = asString(hit.chunk_id)
      ?? `${asString(hit.book_slug) ?? 'unknown'}::${asString(hit.section) ?? 'unknown'}`;
    const existing = rows.get(key);
    if (existing) return existing;
    const created: ForensicHitRow = {
      key,
      bookSlug: asString(hit.book_slug) ?? 'unknown',
      section: asString(hit.section) ?? '',
      bm25Rank: null,
      vectorRank: null,
      hybridRank: null,
      rerankRank: null,
      bm25Score: null,
      vectorScore: null,
      fusedScore: asNumber(hit.fused_score),
      survived: false,
    };
    rows.set(key, created);
    return created;
  };

  stages.bm25.forEach((hit, index) => {
    const row = ensureRow(hit);
    const componentScores = asRecord(hit.component_scores);
    row.bm25Rank = index + 1;
    row.bm25Score = asNumber(componentScores.bm25_score)
      ?? asNumber(componentScores.overlay_bm25_score)
      ?? asNumber(hit.raw_score);
  });
  stages.vector.forEach((hit, index) => {
    const row = ensureRow(hit);
    const componentScores = asRecord(hit.component_scores);
    row.vectorRank = index + 1;
    row.vectorScore = asNumber(componentScores.vector_score) ?? asNumber(hit.raw_score);
  });
  stages.hybrid.forEach((hit, index) => {
    const row = ensureRow(hit);
    row.hybridRank = index + 1;
    row.fusedScore = asNumber(hit.fused_score) ?? row.fusedScore;
    row.survived = true;
  });
  stages.reranked.forEach((hit, index) => {
    const row = ensureRow(hit);
    row.rerankRank = index + 1;
    row.fusedScore = asNumber(hit.fused_score) ?? row.fusedScore;
    row.survived = true;
  });

  return Array.from(rows.values())
    .filter((row) => row.survived)
    .sort((left, right) => {
    const leftRank = left.rerankRank ?? left.hybridRank ?? left.bm25Rank ?? left.vectorRank ?? 9999;
    const rightRank = right.rerankRank ?? right.hybridRank ?? right.bm25Rank ?? right.vectorRank ?? 9999;
    if (leftRank !== rightRank) return leftRank - rightRank;
    return left.bookSlug.localeCompare(right.bookSlug) || left.section.localeCompare(right.section);
    });
}

function formatRank(rank: number | null): string {
  return rank ? `#${rank}` : '–';
}

function formatShift(fromRank: number | null, toRank: number | null): string {
  if (!fromRank && !toRank) return '–';
  if (!fromRank && toRank) return `new→#${toRank}`;
  if (fromRank && !toRank) return `#${fromRank}→out`;
  if (fromRank === toRank) return `#${toRank}`;
  return `#${fromRank}→#${toRank}`;
}

function truncateText(value: string, max = 72): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

function summarizeUnknown(value: unknown): string {
  if (typeof value === 'string') return truncateText(value, 72);
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (Array.isArray(value)) return `array(${value.length})`;
  if (value && typeof value === 'object') return `object(${Object.keys(asRecord(value)).length})`;
  if (value === null) return 'null';
  return String(value);
}

function summarizeMeta(meta: Record<string, unknown>, limit = 8): string[] {
  return Object.entries(meta)
    .slice(0, limit)
    .map(([key, value]) => `${key}=${summarizeUnknown(value)}`);
}

function stageWidthFor(durationMs: number | null, maxDuration: number): number {
  const MIN = 92;
  const MAX = 220;
  if (durationMs === null || maxDuration <= 0) return MIN;
  const ratio = Math.min(1, Math.max(0.05, durationMs / maxDuration));
  return Math.round(MIN + (MAX - MIN) * ratio);
}

function severityToTone(severity: Severity): 'pass' | 'watch' | 'risk' | 'info' {
  if (severity === 'ok') return 'pass';
  if (severity === 'watch') return 'watch';
  if (severity === 'risk') return 'risk';
  return 'info';
}

function verdictToTone(verdict: Verdict): 'pass' | 'watch' | 'risk' | 'info' {
  switch (verdict) {
    case 'Grounded': return 'pass';
    case 'Review':   return 'watch';
    case 'NoAnswer': return 'risk';
    default:         return 'info';
  }
}

const SEVERITY_LABEL: Record<Severity, string> = {
  ok: '안정',
  watch: '주의',
  risk: '위험',
  pending: '대기',
};

const VERDICT_LABEL: Record<Verdict, string> = {
  Grounded: '근거 확보',
  Review: '검토 필요',
  NoAnswer: '답변 불가',
  Pending: '진행 중',
};

function ScoreIcon({ outcome }: { outcome: ScorecardItem['outcome'] }) {
  if (outcome === 'pass') return <Check size={14} aria-hidden="true" />;
  if (outcome === 'fail') return <XCircle size={14} aria-hidden="true" />;
  if (outcome === 'n/a') return <Minus size={14} aria-hidden="true" />;
  return <Loader2 size={14} className="wtp-spin" aria-hidden="true" />;
}

export default function WorkspaceTracePanel({
  query,
  events,
  result,
  isSending,
}: WorkspaceTracePanelProps) {
  const [view, setView] = useState<ViewMode>('explain');
  const [activeStep, setActiveStep] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const stages = useMemo(() => collapseStages(events), [events]);
  const stageMap = useMemo(() => {
    const map = new Map<string, DerivedStage>();
    stages.forEach((s) => map.set(s.step, s));
    return map;
  }, [stages]);

  const verdict = deriveVerdict(result ?? null);
  const { severity, signals } = deriveSeverity(result ?? null, events);
  const scorecard = useMemo(() => evaluateScorecard(result ?? null), [result]);
  const scorecardSummary = useMemo(() => summarizeScorecard(scorecard), [scorecard]);

  const pipelineTrace = asRecord(result?.pipeline_trace);
  const retrievalTrace = asRecord(result?.retrieval_trace);
  const timings = asRecord(pipelineTrace.timings_ms);
  const totalMs = asNumber(timings.total);
  const selection = asRecord(pipelineTrace.selection);
  const selectedHits = asArray(selection.selected_hits)
    .map((hit) => asRecord(hit))
    .filter((hit) => Object.keys(hit).length > 0);
  const llm = asRecord(pipelineTrace.llm);
  const metrics = asRecord(retrievalTrace.metrics);
  const reranker = asRecord(retrievalTrace.reranker);
  const plan = asRecord(retrievalTrace.plan);
  const forensicHitRows = deriveForensicHitRows(retrievalTrace);
  const explain = useMemo(() => deriveWorkspaceExplain({ query, result }), [query, result]);
  const decomposed = asArray(retrievalTrace.decomposed_queries)
    .map((q) => (typeof q === 'string' ? q : ''))
    .filter(Boolean);
  const selectedStep = isSending ? null : activeStep;
  const isCopied = !isSending && copied;

  const rewritten = asString(result?.rewritten_query);
  const showRewritten = Boolean(rewritten && rewritten !== query);

  // Pre-compute timeline real estate.
  const timelineStages = stages.filter(
    (s) => TIMELINE_STEPS.includes(s.step) || s.step === 'stream_error',
  );
  const maxDuration = Math.max(0, ...timelineStages.map((s) => s.durationMs ?? 0));

  const sessionId = result?.session_id;
  const responseKind = result?.response_kind;

  // ---- handlers ---------------------------------------------------------

  function toggleStage(step: string): void {
    setActiveStep((cur) => (cur === step ? null : step));
  }

  async function handleCopy(): Promise<void> {
    const payload = {
      query,
      rewritten_query: result?.rewritten_query ?? null,
      response_kind: responseKind ?? null,
      session_id: sessionId ?? null,
      verdict,
      severity,
      signals,
      scorecard,
      citations: (result?.citations ?? []).map((citation) => ({
        book_slug: citation.book_slug,
        section: citation.section,
        section_path: citation.section_path,
        viewer_path: citation.viewer_path,
        source_lane: citation.source_lane,
        boundary_truth: citation.boundary_truth,
      })),
      warnings: result?.warnings ?? [],
      timeline: timelineStages.map((stage) => ({
        step: stage.step,
        status: stage.status,
        label: stage.label,
        detail: stage.detail,
        duration_ms: stage.durationMs,
      })),
      retrieval_summary: {
        decomposed_queries: decomposed,
        metrics,
        reranker: {
          enabled: Boolean(reranker.enabled),
          applied: Boolean(reranker.applied),
          mode: asString(reranker.mode),
          decision_reason: asString(reranker.decision_reason),
          top1_changed: Boolean(reranker.top1_changed),
          rebalance_reasons: asArray(reranker.rebalance_reasons).map(String),
        },
        graph: asRecord(retrievalTrace.graph),
        selected_hits: selectedHits.slice(0, 5).map((hit) => ({
          book_slug: asString(hit.book_slug),
          section: asString(hit.section),
          fused_score: asNumber(hit.fused_score),
        })),
      },
      pipeline_summary: {
        timings_ms: timings,
        llm: {
          provider: asString(llm.last_provider) ?? asString(llm.preferred_provider),
          fallback_used: Boolean(llm.last_fallback_used),
          attempted_providers: asArray(llm.last_attempted_providers).map(String),
        },
      },
      events: events.map((event) => ({
        step: event.step,
        status: event.status,
        label: event.label,
        detail: event.detail,
        duration_ms: event.duration_ms ?? null,
        timestamp_ms: event.timestamp_ms ?? null,
        meta_summary: summarizeMeta(asRecord(event.meta)),
      })),
    };
    try {
      await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch (err) {
      console.error('Trace copy failed', err);
    }
  }

  // ---- render -----------------------------------------------------------

  const hasAnyEvent = stages.length > 0 || isSending;

  return (
    <section className="wtp" aria-live="polite" aria-label="Test mode trace panel">
      <header className="wtp-header">
        <span className="wtp-kicker">TEST</span>
        <h2 className="wtp-title">Pipeline Audit</h2>
        <span className="wtp-session">session · {shortSession(sessionId)}</span>
        <div className="wtp-pill-group">
          <span className="wtp-pill" data-tone={verdictToTone(verdict)}>
            <span className="wtp-dot" aria-hidden="true" />
            <span>{VERDICT_LABEL[verdict]}</span>
          </span>
          <span className="wtp-pill" data-tone={severityToTone(severity)} title={signals.join(' · ') || '신호 없음'}>
            <span className="wtp-dot" aria-hidden="true" />
            <span>{SEVERITY_LABEL[severity]}</span>
          </span>
          <span className="wtp-pill" data-tone="info">
            <span>{formatMs(totalMs, isSending ? '…' : '–')}</span>
          </span>
          {responseKind ? (
            <span className="wtp-pill">
              <span>{responseKind}</span>
            </span>
          ) : null}
          <div className="wtp-toggle" role="group" aria-label="View mode">
            <button
              type="button"
              aria-pressed={view === 'explain'}
              onClick={() => setView('explain')}
            >
              Explain
            </button>
            <button
              type="button"
              aria-pressed={view === 'overview'}
              onClick={() => setView('overview')}
            >
              Overview
            </button>
            <button
              type="button"
              aria-pressed={view === 'forensic'}
              onClick={() => setView('forensic')}
            >
              Forensic
            </button>
          </div>
        </div>
      </header>

      {/* --- Question banner ------------------------------------------ */}
      <div className="wtp-question">
        <div className="wtp-question-row">
          <span className="wtp-question-label">Question</span>
          <span className="wtp-question-text">{query || '아직 질문이 없습니다.'}</span>
        </div>
        {view !== 'explain' && showRewritten ? (
          <div className="wtp-question-row">
            <span className="wtp-question-label">Rewritten</span>
            <span className="wtp-question-text is-rewritten">{rewritten}</span>
          </div>
        ) : null}
        {view !== 'explain' && decomposed.length > 0 ? (
          <div className="wtp-question-row" style={{ alignItems: 'flex-start' }}>
            <span className="wtp-question-label">Subqueries</span>
            <div className="wtp-subqueries">
              {decomposed.map((sq, i) => (
                <span key={`${sq}-${i}`} className="wtp-subquery-chip">{sq}</span>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      {view === 'explain' ? (
        <div className="wtp-explain">
          <div className="wtp-explain-head">
            <span className="wtp-section-title">Explain</span>
          </div>
          <div className="wtp-explain-stages">
            {explain.stages.map((stage, index) => (
              <article key={stage.id} className="wtp-explain-stage">
                <span className="wtp-explain-stage-step">{index + 1}</span>
                <div className="wtp-explain-stage-body">
                  <h3 className="wtp-explain-stage-title">{stage.title}</h3>
                  <p className="wtp-explain-stage-summary">{stage.summary}</p>
                </div>
              </article>
            ))}
          </div>

          <div className="wtp-explain-grid">
            <article className="wtp-explain-card">
              <div className="wtp-explain-card-title">질문 분류</div>
              <h3>{explain.questionTypeLabel}</h3>
              <p className="wtp-explain-card-body">{explain.questionTypeBody}</p>
            </article>

            <article className="wtp-explain-card">
              <div className="wtp-explain-card-title">Rewrite</div>
              <p className="wtp-explain-card-body">{explain.rewriteBody}</p>
            </article>

            <article className="wtp-explain-card">
              <div className="wtp-explain-card-title">검색 전략</div>
              <p className="wtp-explain-card-body">{explain.searchBody}</p>
            </article>

            <article className="wtp-explain-card">
              <div className="wtp-explain-card-title">Graph / Rerank</div>
              <p className="wtp-explain-card-body">{explain.decisionBody}</p>
            </article>

            <article className="wtp-explain-card">
              <div className="wtp-explain-card-title">최종 근거</div>
              <p className="wtp-explain-card-body">{explain.evidenceBody}</p>
              {explain.evidenceItems.length > 0 ? (
                <div className="wtp-explain-evidence">
                  {explain.evidenceItems.map((item) => (
                    <div key={item.label} className="wtp-explain-evidence-item">
                      <strong className="wtp-explain-evidence-label">{item.label}</strong>
                      <span className="wtp-explain-evidence-reason">{item.reason}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </article>
          </div>
        </div>
      ) : (
        <>
          {/* --- Stage timeline ------------------------------------------ */}
          <div className="wtp-timeline-wrap">
            <div className="wtp-timeline-head">
              <span className="wtp-section-title">
                Pipeline <strong>{timelineStages.length}/{TIMELINE_STEPS.length} stages</strong>
              </span>
              {isSending ? (
                <span className="wtp-pill" data-tone="info" aria-live="polite">
                  <span className="wtp-pulse" aria-hidden="true" /> 스트리밍 중…
                </span>
              ) : null}
            </div>

            {timelineStages.length === 0 ? (
              <div className="wtp-empty">
                <strong>대기 중</strong>
                <span>질문을 보내면 백엔드 트레이스가 단계별로 채워집니다.</span>
              </div>
            ) : (
              <div className="wtp-timeline">
                {timelineStages.map((stage) => (
                  <button
                    key={stage.step}
                    type="button"
                    className="wtp-stage"
                    data-status={stage.status}
                    data-active={selectedStep === stage.step}
                    style={{ width: stageWidthFor(stage.durationMs, maxDuration) }}
                    onClick={() => toggleStage(stage.step)}
                    aria-pressed={selectedStep === stage.step}
                    aria-label={`${stage.label} ${stage.status} ${formatMs(stage.durationMs)}`}
                  >
                    <span className="wtp-stage-top">
                      <span className="wtp-stage-status" aria-hidden="true" />
                      <span className="wtp-stage-time">{formatMs(stage.durationMs)}</span>
                    </span>
                    <span className="wtp-stage-label">{stage.label}</span>
                    <span className="wtp-stage-bar" aria-hidden="true">
                      <span
                        style={{
                          width: `${Math.min(100, Math.max(8, ((stage.durationMs ?? 0) / Math.max(1, maxDuration)) * 100))}%`,
                        }}
                      />
                    </span>
                  </button>
                ))}
              </div>
            )}

            {selectedStep ? (() => {
              const stage = stageMap.get(selectedStep);
              if (!stage) return null;
              const metaEntries = Object.entries(stage.meta);
              return (
                <div className="wtp-stage-detail">
                  <div className="wtp-stage-detail-title">{stage.step} · {stage.status}</div>
                  {stage.detail ? <div style={{ marginBottom: 10, color: '#f0f4fa' }}>{stage.detail}</div> : null}
                  {metaEntries.length === 0 ? (
                    <div className="wtp-stage-detail-empty">메타 데이터 없음</div>
                  ) : (
                    <dl className="wtp-stage-detail-body">
                      {metaEntries.map(([key, value]) => (
                        <Fragment key={key}>
                          <dt>{key}</dt>
                          <dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd>
                        </Fragment>
                      ))}
                    </dl>
                  )}
                </div>
              );
            })() : null}
          </div>

          {/* --- Cards ----------------------------------------------------- */}
          <div className="wtp-grid">
            {/* Citations */}
            <article className="wtp-card">
              <div className="wtp-card-header">
                <span className="wtp-card-title">Citations · 근거</span>
                <span className="wtp-card-meta">selected {selectedHits.length}</span>
              </div>
              {selectedHits.length === 0 ? (
                <p>아직 선택된 근거가 없습니다.</p>
              ) : (
                <div className="wtp-citations">
                  {selectedHits.slice(0, 3).map((hit, idx) => {
                    const matchingCitation = (result?.citations ?? []).find(
                      (c) => c.book_slug === hit.book_slug && (c.section_path ?? c.section) === hit.section,
                    );
                    const lane = (matchingCitation?.source_lane ?? 'official').toLowerCase();
                    return (
                      <div key={`${hit.book_slug}-${idx}`} className="wtp-citation">
                        <div className="wtp-citation-top">
                          <span className="wtp-citation-index">#{idx + 1}</span>
                          <span className="wtp-citation-book">{String(hit.book_slug ?? 'unknown')}</span>
                          <span className="wtp-lane-badge" data-lane={lane}>
                            {lane}
                          </span>
                          <span className="wtp-citation-score">
                            score {asNumber(hit.fused_score)?.toFixed(3) ?? '–'}
                          </span>
                        </div>
                        <span className="wtp-citation-section">{String(hit.section ?? '')}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </article>

            {/* Retrieval & Reranker */}
            <article className="wtp-card">
              <div className="wtp-card-header">
                <span className="wtp-card-title">Retrieval · 검색</span>
                <span className="wtp-card-meta">
                  {asNumber(plan.decomposed_query_count) ? `subq ${plan.decomposed_query_count}` : 'single q'}
                </span>
              </div>
              <div className="wtp-metric-row">
                <span>BM25 <strong>{asNumber(asRecord(metrics.bm25).count) ?? 0}</strong></span>
                <span>Vector <strong>{asNumber(asRecord(metrics.vector).count) ?? 0}</strong></span>
                <span>Hybrid <strong>{asNumber(asRecord(metrics.hybrid).count) ?? 0}</strong></span>
                <span>Reranked <strong>{asNumber(asRecord(metrics.reranked).count) ?? 0}</strong></span>
              </div>
              {reranker.applied ? (
                <div className="wtp-rerank">
                  <div className="wtp-rerank-top">
                    {String(reranker.top1_before ?? '?')}
                    <span className="wtp-rerank-arrow">→</span>
                    <strong>{String(reranker.top1_after ?? '?')}</strong>
                    <span className="wtp-card-meta">
                      {reranker.top1_changed ? 'changed' : 'unchanged'}
                    </span>
                  </div>
                  {asArray(reranker.rebalance_reasons).length > 0 ? (
                    <div className="wtp-rerank-reasons">
                      {asArray(reranker.rebalance_reasons).slice(0, 6).map((reason, i) => (
                        <span key={`${String(reason)}-${i}`} className="wtp-reason-chip">
                          {String(reason)}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : (
                <p>리랭커 비활성 또는 미적용.</p>
              )}
            </article>

            {/* Generation */}
            <article className="wtp-card">
              <div className="wtp-card-header">
                <span className="wtp-card-title">Generation · 생성</span>
                <span className="wtp-card-meta">
                  {formatMs(timings.llm_generate_total ?? timings.deterministic_total)}
                </span>
              </div>
              <h3>
                {String(llm.last_provider ?? llm.preferred_provider ?? (stageMap.has('deterministic_answer') ? 'Deterministic (rule)' : 'pending'))}
              </h3>
              <div className="wtp-metric-row">
                <span>Fallback <strong>{llm.last_fallback_used ? 'used' : 'no'}</strong></span>
                <span>
                  Attempted <strong>{asArray(llm.last_attempted_providers).length || (llm.last_provider ? 1 : 0)}</strong>
                </span>
              </div>
              {asArray(llm.last_attempted_providers).length > 1 ? (
                <p>경로: {asArray(llm.last_attempted_providers).map(String).join(' → ')}</p>
              ) : null}
            </article>

            {/* Product Gate */}
            <article className="wtp-card">
              <div className="wtp-card-header">
                <span className="wtp-card-title">Product Gate · 계약 채점</span>
                <span className="wtp-card-meta">
                  {scorecardSummary.pass}/{scorecardSummary.pass + scorecardSummary.fail} pass
                  {scorecardSummary.na > 0 ? ` · ${scorecardSummary.na} n/a` : ''}
                </span>
              </div>
              <div className="wtp-scorecard">
                {scorecard.map((item) => (
                  <div key={item.id} className="wtp-scoreitem" data-outcome={item.outcome}>
                    <span className="wtp-score-icon" aria-hidden="true">
                      <ScoreIcon outcome={item.outcome} />
                    </span>
                    <span className="wtp-score-body">
                      <span className="wtp-score-label">
                        <span className="wtp-score-id">{item.id}</span>
                        {item.label}
                      </span>
                      <span className="wtp-score-rationale" title={item.question}>
                        {item.rationale}
                      </span>
                    </span>
                    <span className="wtp-score-mode">{item.mode}</span>
                  </div>
                ))}
              </div>
              <div className="wtp-score-summary">
                <strong>
                  {scorecardSummary.passRate === null
                    ? '평가 대기'
                    : `${Math.round(scorecardSummary.passRate * 100)}% pass`}
                </strong>
                <span>· product gate ≥ 90% (5턴 누적)</span>
              </div>
            </article>
          </div>
        </>
      )}

      {/* --- Forensic view ------------------------------------------- */}
      {view === 'forensic' ? (
        <div className="wtp-forensic">
          <div className="wtp-forensic-head">
            <span className="wtp-section-title">
              Forensic <strong>structured runtime audit</strong>
            </span>
            <button
              type="button"
              className="wtp-copy-btn"
              data-copied={isCopied}
              onClick={() => void handleCopy()}
              disabled={!hasAnyEvent}
            >
              {isCopied ? <CheckCircle2 size={14} /> : <ClipboardCopy size={14} />}
              {isCopied ? 'Copied' : 'Copy audit summary'}
            </button>
          </div>

          {/* All events */}
          <div className="wtp-events-table" role="table" aria-label="All trace events">
            <span className="wtp-events-head" role="columnheader">t+ms</span>
            <span className="wtp-events-head" role="columnheader">dur</span>
            <span className="wtp-events-head" role="columnheader">step · status</span>
            <span className="wtp-events-head" role="columnheader">detail · meta</span>
            {events.length === 0 ? (
              <span className="wtp-events-cell" style={{ gridColumn: '1 / -1', color: 'var(--text-dim)' }}>
                no events
              </span>
            ) : (
              events.map((event, idx) => {
                const metaSummary = summarizeMeta(asRecord(event.meta));
                const statusClass = event.status === 'error'
                  ? 'is-error'
                  : event.status === 'running'
                    ? 'is-running'
                    : '';
                return (
                  <Fragment key={`${event.step}-${idx}`}>
                    <span className="wtp-events-cell">{formatMs(event.timestamp_ms, '–')}</span>
                    <span className="wtp-events-cell">{formatMs(event.duration_ms, '–')}</span>
                    <span className={`wtp-events-cell is-step ${statusClass}`}>
                      {event.step}
                      <br />
                      <span style={{ color: 'var(--text-dim)', fontSize: '0.62rem' }}>
                        {event.status}
                      </span>
                    </span>
                    <span className="wtp-events-cell">
                      {event.label && event.label !== event.step ? (
                        <span style={{ color: '#f0f4fa' }}>{event.label}</span>
                      ) : null}
                      {event.detail ? (
                        <>
                          {event.label && event.label !== event.step ? <br /> : null}
                          {event.detail}
                        </>
                      ) : null}
                      {metaSummary.length > 0 ? (
                        <div style={{ marginTop: 6, color: 'var(--text-dim)', fontSize: '0.68rem' }}>
                          {metaSummary.join(' · ')}
                        </div>
                      ) : null}
                    </span>
                  </Fragment>
                );
              })
            )}
          </div>

          {/* Timings */}
          {Object.keys(timings).length > 0 ? (
            <div className="wtp-timings">
              {Object.entries(timings).map(([key, ms]) => (
                <div key={key} className="wtp-timing">
                  <span>{key}</span>
                  <strong>{formatMs(ms)}</strong>
                </div>
              ))}
            </div>
          ) : null}

          {forensicHitRows.length > 0 ? (
            <div className="wtp-scoretable-wrap">
              <div className="wtp-card-header">
                <span className="wtp-card-title">Retrieval Score Audit</span>
                <span className="wtp-card-meta">{forensicHitRows.length} hits</span>
              </div>
              <div className="wtp-scoretable" role="table" aria-label="Retrieval score audit">
                <span className="wtp-scoretable-head" role="columnheader">hit</span>
                <span className="wtp-scoretable-head" role="columnheader">BM25</span>
                <span className="wtp-scoretable-head" role="columnheader">Vector</span>
                <span className="wtp-scoretable-head" role="columnheader">B→H</span>
                <span className="wtp-scoretable-head" role="columnheader">H→R</span>
                <span className="wtp-scoretable-head" role="columnheader">Fused</span>
                {forensicHitRows.map((row) => (
                  <Fragment key={row.key}>
                    <span className="wtp-scoretable-cell is-hit">
                      <strong>{row.bookSlug}</strong>
                      <span>{row.section || 'section 없음'}</span>
                    </span>
                    <span className="wtp-scoretable-cell">
                      {formatRank(row.bm25Rank)}
                      <em>{formatScore(row.bm25Score)}</em>
                    </span>
                    <span className="wtp-scoretable-cell">
                      {formatRank(row.vectorRank)}
                      <em>{formatScore(row.vectorScore)}</em>
                    </span>
                    <span className="wtp-scoretable-cell">
                      {formatShift(
                        (() => {
                          const ranks = [row.bm25Rank, row.vectorRank].filter((value): value is number => value !== null);
                          if (ranks.length === 0) return null;
                          return Math.min(...ranks);
                        })(),
                        row.hybridRank,
                      )}
                    </span>
                    <span className="wtp-scoretable-cell">
                      {formatShift(row.hybridRank, row.rerankRank)}
                    </span>
                    <span className="wtp-scoretable-cell">
                      {formatScore(row.fusedScore)}
                    </span>
                  </Fragment>
                ))}
              </div>
            </div>
          ) : null}

          {result?.warnings && result.warnings.length > 0 ? (
            <div className="wtp-card">
              <div className="wtp-card-header">
                <span className="wtp-card-title" style={{ color: 'var(--wtp-risk)' }}>
                  <AlertTriangle size={14} style={{ verticalAlign: 'middle', marginRight: 4 }} />
                  Warnings · {result.warnings.length}
                </span>
              </div>
              <ul style={{ margin: 0, paddingLeft: 18, color: 'var(--text-muted)', fontSize: '0.82rem' }}>
                {result.warnings.map((warn, i) => (
                  <li key={i}>{warn}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
