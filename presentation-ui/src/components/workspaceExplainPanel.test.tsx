import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { ChatResponse } from '../lib/runtimeApi';
import WorkspaceTracePanel from './WorkspaceTracePanel';

function makeResponse(): ChatResponse {
  return {
    answer: 'answer',
    rewritten_query: 'OpenShift 아키텍처 | 개요 | 플랫폼',
    citations: [
      {
        index: 1,
        book_slug: 'architecture',
        section: 'OpenShift 아키텍처 개요',
        section_path: 'OpenShift 아키텍처 개요',
        viewer_path: '/wiki/architecture#overview',
        source_lane: 'official',
      },
    ],
    warnings: [],
    session_id: 'session-1',
    response_kind: 'rag',
    suggested_queries: [],
    related_links: [],
    related_sections: [],
    retrieval_trace: {
      plan: {
        normalized_query: 'OpenShift 아키텍처 설명',
        rewritten_query: 'OpenShift 아키텍처 | 개요 | 플랫폼',
        rewrite_applied: true,
        rewrite_reason: 'short_contextual_query',
      },
      metrics: {
        bm25: { count: 8 },
        vector: { count: 8 },
        hybrid: { count: 5 },
        reranked: { count: 5 },
      },
      ablation: {
        top_support: 'both',
        bm25_vector_overlap_count: 2,
      },
      graph: {
        adapter_mode: 'skipped',
        fallback_reason: 'not_needed',
      },
      reranker: {
        enabled: true,
        applied: false,
        mode: 'skipped',
        decision_reason: 'confident_explanation_hybrid_top_hit',
        top1_changed: false,
      },
    },
    pipeline_trace: {
      selection: {
        selected_hits: [
          {
            book_slug: 'architecture',
            section: 'OpenShift 아키텍처 개요',
            bm25_score: 8.4,
            vector_score: 0.92,
          },
        ],
      },
      timings_ms: {},
      llm: {},
    },
  };
}

describe('WorkspaceTracePanel explain mode', () => {
  it('renders explain summaries by default without forensic blocks', () => {
    const html = renderToStaticMarkup(
      <WorkspaceTracePanel
        query="OpenShift 아키텍처를 설명해줘"
        events={[]}
        result={makeResponse()}
        isSending={false}
      />,
    );

    expect(html).toContain('Explain');
    expect(html).toContain('질문 분류');
    expect(html).toContain('검색 전략');
    expect(html).toContain('Graph / Rerank');
    expect(html).toContain('최종 근거');
    expect(html).not.toContain('Citations · 근거');
    expect(html).not.toContain('Retrieval · 검색');
    expect(html).not.toContain('Retrieval Score Audit');
    expect(html).not.toContain('raw runtime payload');
  });
});
