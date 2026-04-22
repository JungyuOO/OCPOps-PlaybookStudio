import { describe, expect, it } from 'vitest';
import type { ChatResponse } from '../lib/runtimeApi';
import { deriveWorkspaceExplain } from './workspaceExplain';

function makeResponse(overrides: Partial<ChatResponse> = {}): ChatResponse {
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
      {
        index: 2,
        book_slug: 'overview',
        section: '플랫폼 개요',
        section_path: '플랫폼 개요',
        viewer_path: '/wiki/overview#platform-overview',
        source_lane: 'official',
      },
    ],
    warnings: [],
    session_id: 'session-1',
    suggested_queries: [],
    related_links: [],
    related_sections: [],
    response_kind: 'rag',
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
          {
            book_slug: 'overview',
            section: '플랫폼 개요',
            bm25_score: 7.8,
            vector_score: 0.88,
          },
        ],
      },
    },
    ...overrides,
  };
}

describe('workspaceExplain', () => {
  it('summarizes explainer questions in human-readable sentences', () => {
    const explain = deriveWorkspaceExplain({
      query: 'OpenShift 아키텍처를 설명해줘',
      result: makeResponse(),
    });

    expect(explain.questionTypeLabel).toBe('설명형');
    expect(explain.questionTypeBody).toContain('설명형 개념 질문');
    expect(explain.rewriteBody).toContain('검색어는 `OpenShift 아키텍처 | 개요 | 플랫폼` 형태로 보강됐다.');
    expect(explain.rewriteBody).toContain('`개요`, `플랫폼`');
    expect(explain.searchBody).toContain('BM25와 Vector를 함께 사용했고, 상위 후보는 두 신호를 함께 받았다.');
    expect(explain.decisionBody).toContain('graph expand는 생략됐다.');
    expect(explain.decisionBody).toContain('rerank는 미적용됐다.');
    expect(explain.evidenceBody).toContain('architecture / OpenShift 아키텍처 개요');
    expect(explain.evidenceItems[0]?.reason).toContain('BM25와 Vector가 함께 지지한 상위 근거였다.');
    expect(explain.stages.map((stage) => stage.title)).toEqual([
      '질문 해석',
      '근거 검색',
      '답변 결정',
      '최종 근거',
    ]);
  });

  it('explains bounded graph fallback and rerank application without raw payload labels', () => {
    const explain = deriveWorkspaceExplain({
      query: '그거 어떻게 확인해?',
      result: makeResponse({
        rewritten_query: 'OCP 4.20 | 주제 Ingress Operator | 그거 어떻게 확인해?',
        citations: [
          {
            index: 1,
            book_slug: 'ingress',
            section: 'Ingress Operator 확인 절차',
            section_path: 'Ingress Operator 확인 절차',
            viewer_path: '/wiki/ingress#verify',
            source_lane: 'official',
          },
        ],
        retrieval_trace: {
          plan: {
            normalized_query: '그거 어떻게 확인해?',
            rewritten_query: 'OCP 4.20 | 주제 Ingress Operator | 그거 어떻게 확인해?',
            rewrite_applied: true,
            rewrite_reason: 'follow_up_reference',
          },
          metrics: {
            bm25: { count: 6 },
            vector: { count: 8 },
            hybrid: { count: 5 },
          },
          ablation: {
            top_support: 'vector',
            bm25_vector_overlap_count: 1,
          },
          graph: {
            adapter_mode: 'local_sidecar',
            fallback_reason: 'neo4j_unhealthy:connect failed: timed out|sidecar_eager_load_skipped:file_too_large:7876461484',
          },
          reranker: {
            enabled: true,
            applied: true,
            mode: 'model',
            decision_reason: 'semantic_intent',
            top1_changed: true,
            rebalance_reasons: ['derived_or_non_core_hits'],
          },
        },
        pipeline_trace: {
          selection: {
            selected_hits: [
              {
                book_slug: 'ingress',
                section: 'Ingress Operator 확인 절차',
                vector_score: 0.94,
              },
            ],
          },
        },
      }),
    });

    expect(explain.questionTypeLabel).toBe('절차형');
    expect(explain.rewriteBody).toContain('이전 대화 맥락을 복원해야 했기 때문이다.');
    expect(explain.searchBody).toContain('Vector 쪽 후보가 더 강했다.');
    expect(explain.decisionBody).toContain('local fallback으로 관계를 보강했다.');
    expect(explain.decisionBody).toContain('bounded local fallback으로 내려갔다.');
    expect(explain.decisionBody).toContain('대용량 sidecar 전체 로드는 피하고 compact 또는 bounded 경로만 사용했다.');
    expect(explain.decisionBody).toContain('rerank는 semantic model을 적용했다.');
    expect(explain.decisionBody).toContain('상위 1개 후보는 이 단계에서 다시 정렬됐다.');
    expect(explain.evidenceItems[0]?.reason).toContain('Vector 쪽 의미 검색이 주도한 상위 근거였다.');
    expect(explain.decisionBody).not.toContain('fallback_reason');
    expect(explain.decisionBody).not.toContain('decision_reason');
  });
});
