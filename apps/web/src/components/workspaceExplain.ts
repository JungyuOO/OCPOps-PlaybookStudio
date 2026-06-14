import type { ChatCitation, ChatResponse } from '../lib/runtimeApi';

export interface ExplainStage {
  id: string;
  title: string;
  summary: string;
}

export interface ExplainEvidenceItem {
  label: string;
  reason: string;
}

export interface WorkspaceExplainModel {
  questionTypeLabel: string;
  questionTypeBody: string;
  rewriteBody: string;
  searchBody: string;
  decisionBody: string;
  evidenceBody: string;
  evidenceItems: ExplainEvidenceItem[];
  stages: ExplainStage[];
}

interface DeriveWorkspaceExplainInput {
  query: string;
  result?: ChatResponse | null;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim().length > 0 ? value.trim() : null;
}

function normalizeText(value: string): string {
  return value.replace(/\s+/g, ' ').trim();
}

function tokenize(value: string): string[] {
  return normalizeText(value)
    .toLowerCase()
    .split(/[^0-9a-zA-Z가-힣._-]+/)
    .map((token) => token.trim())
    .filter((token) => token.length >= 2);
}

function uniqueStrings(values: string[], limit = values.length): string[] {
  const seen = new Set<string>();
  const items: string[] = [];
  values.forEach((value) => {
    const normalized = value.trim();
    if (!normalized || seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    if (items.length < limit) {
      items.push(normalized);
    }
  });
  return items;
}

function quotedList(values: string[]): string {
  return uniqueStrings(values).map((value) => `\`${value}\``).join(', ');
}

function truncate(value: string, limit = 150): string {
  return value.length > limit ? `${value.slice(0, limit - 1)}…` : value;
}

function includesAny(text: string, tokens: string[]): boolean {
  const lowered = text.toLowerCase();
  return tokens.some((token) => lowered.includes(token.toLowerCase()));
}

function humanizeRewriteReason(reason: string): string {
  switch (reason) {
    case 'follow_up_reference':
      return '이전 대화 맥락을 복원해야 했기 때문이다.';
    case 'short_contextual_query':
      return '질문이 짧아 주제와 목표를 함께 붙여야 검색이 안정적이기 때문이다.';
    case 'explicit_topic_signal':
      return '질문 자체에 주제가 이미 명확해 추가 보강이 필요하지 않았기 때문이다.';
    case 'generic_intro_query':
      return '소개형 질문이라 원문만으로도 개념 문서를 찾기 충분했기 때문이다.';
    case 'no_context':
      return '붙일 문맥 정보가 아직 없었기 때문이다.';
    case 'no_rewrite_needed':
      return '원문만으로도 검색 의도가 충분히 드러났기 때문이다.';
    case 'empty_query':
      return '질문 본문이 비어 있어 검색어를 보강할 수 없었기 때문이다.';
    default:
      return '검색 의도를 더 선명하게 만들기 위한 정리 단계였다.';
  }
}

function humanizeRerankDecision(reason: string): string {
  switch (reason) {
    case 'derived_or_non_core_hits':
      return '파생 문서나 비코어 후보가 섞여 추가 판별이 필요했기 때문이다.';
    case 'follow_up_reference':
      return '이전 대화 맥락을 복원해야 했기 때문이다.';
    case 'heuristic_first_intent':
      return '절차형 운영 질문이라 규칙 기반 재정렬이 먼저였기 때문이다.';
    case 'confident_explanation_hybrid_top_hit':
      return 'hybrid 상위 근거가 이미 충분히 명확했기 때문이다.';
    case 'semantic_intent':
      return '개념 차이나 의미 구분이 필요한 질문이기 때문이다.';
    case 'small_candidate_set':
      return '후보 수가 적고 상위 문서가 한쪽으로 모였기 때문이다.';
    case 'cross_book_ambiguity':
      return '여러 책이 비슷한 점수로 경쟁해 추가 판별이 필요했기 때문이다.';
    case 'default_model_rerank':
      return '상위 후보의 의미 차이를 한 번 더 정리하기 위해서다.';
    case 'no_hits':
      return '재정렬할 검색 후보가 없었기 때문이다.';
    default:
      return '최종 답변용 근거 순서를 다듬기 위한 판단이었다.';
  }
}

function humanizeGraphReason(reason: string): string {
  switch (reason) {
    case 'not_needed':
      return '상위 근거가 이미 충분히 모여 관계 확장이 필요하지 않았기 때문이다.';
    case 'follow_up_reference':
      return '이전 대화에서 끌어온 맥락을 보강해야 했기 때문이다.';
    case 'decomposed_query':
      return '질문이 여러 하위 질문으로 분해돼 관계 연결이 필요했기 때문이다.';
    case 'graph_worthy_intent':
      return '개념형이나 비교형 질문이라 관계 문맥 보강 가치가 있었기 때문이다.';
    case 'derived_or_non_core_hits':
      return '파생 문서나 비코어 후보가 섞여 관계 확인이 필요했기 때문이다.';
    case 'cross_book_ambiguity':
      return '여러 책이 동시에 경쟁해 관계 기반 보조 판단이 필요했기 때문이다.';
    case 'graph_disabled':
      return '현재 graph runtime이 비활성 상태이기 때문이다.';
    case 'no_hits':
      return '확장할 검색 후보가 없었기 때문이다.';
    default:
      return '관계 보강 필요도를 runtime이 다시 판단한 결과다.';
  }
}

function humanizeGraphFallback(fallbackReason: string): string[] {
  return fallbackReason
    .split('|')
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      if (part.startsWith('neo4j_unhealthy:')) {
        return 'Neo4j 상태가 불안정해 bounded local fallback으로 내려갔다.';
      }
      if (part.startsWith('sidecar_eager_load_skipped:file_too_large:')) {
        return '대용량 sidecar 전체 로드는 피하고 compact 또는 bounded 경로만 사용했다.';
      }
      if (part.startsWith('remote_endpoint_failed:')) {
        return '원격 graph endpoint 대신 local fallback을 사용했다.';
      }
      if (part.startsWith('neo4j_failed:')) {
        return 'Neo4j graph 호출이 실패해 local fallback으로 전환됐다.';
      }
      if (part === 'graph_disabled') {
        return 'graph runtime 자체가 비활성 상태였다.';
      }
      return `그래프 보강은 ${part} 조건을 만나 bounded mode로 처리됐다.`;
    });
}

function extractRewriteHints(query: string, normalizedQuery: string, rewrittenQuery: string): string[] {
  const baseTokens = new Set(tokenize(`${query} ${normalizedQuery}`));
  const segments = rewrittenQuery
    .split('|')
    .map((segment) => normalizeText(segment))
    .filter(Boolean)
    .filter((segment) => segment !== normalizeText(query) && segment !== normalizeText(normalizedQuery));

  const cleanedSegments = segments.map((segment) =>
    segment
      .replace(/^주제\s+/u, '')
      .replace(/^엔터티\s+/u, '')
      .replace(/^미해결 질문\s+/u, '')
      .replace(/^사용자 목표\s+/u, '')
      .trim(),
  );
  const tokenHints = uniqueStrings(
    cleanedSegments.flatMap((segment) => tokenize(segment).filter((token) => !baseTokens.has(token))),
    3,
  );
  if (tokenHints.length > 0) {
    return tokenHints;
  }
  return uniqueStrings(cleanedSegments, 2);
}

function classifyQuestion(query: string): { label: string; body: string } {
  const normalized = normalizeText(query);
  if (!normalized) {
    return {
      label: '미분류',
      body: '질문이 비어 있어 유형을 분류하지 못했다.',
    };
  }
  if (includesAny(normalized, ['비교', '차이', 'vs', 'compare', '어떤 차이', '무엇이 다른'])) {
    return {
      label: '비교형',
      body: '이 질문은 비교형 질문으로 분류됐다. 여러 개념이나 구성요소의 차이를 같은 근거선 위에서 설명해야 하는 유형이다.',
    };
  }
  if (includesAny(normalized, ['어떻게', '절차', '방법', '명령', '설정', '확인', '복구', '해결', '하려면', '해야', 'drain', 'backup', 'restore'])) {
    return {
      label: '절차형',
      body: '이 질문은 절차형 질문으로 분류됐다. 실행 단계나 확인 포인트가 드러나는 근거를 우선 찾는 유형이다.',
    };
  }
  if (includesAny(normalized, ['어디', '위치', '문서', '경로', '찾', '참조'])) {
    return {
      label: '탐색형',
      body: '이 질문은 탐색형 질문으로 분류됐다. 특정 문서나 위치를 빠르게 찾는 쪽이 중요한 유형이다.',
    };
  }
  return {
    label: '설명형',
    body: '이 질문은 설명형 개념 질문으로 분류됐다. 정의, 구조, 배경을 잘 설명하는 문서를 중심으로 답을 만드는 유형이다.',
  };
}

function deriveRewriteBody(
  query: string,
  rewrittenQuery: string | null,
  plan: Record<string, unknown>,
): string {
  const normalizedQuery = asString(plan.normalized_query) ?? query;
  const effectiveRewritten = rewrittenQuery ?? asString(plan.rewritten_query) ?? query;
  const rewriteApplied = Boolean(plan.rewrite_applied);
  const rewriteReason = asString(plan.rewrite_reason) ?? '';
  const reasonBody = humanizeRewriteReason(rewriteReason);

  if (!effectiveRewritten || normalizeText(effectiveRewritten) === normalizeText(query)) {
    return `검색어는 원문을 유지했다. ${reasonBody}`;
  }

  const hints = extractRewriteHints(query, normalizedQuery, effectiveRewritten);
  const hintBody = hints.length > 0
    ? `${quotedList(hints)} 같은 힌트는 관련 문서를 더 안정적으로 찾기 위해 붙었다. `
    : '';

  if (rewriteApplied) {
    return `검색어는 \`${truncate(effectiveRewritten)}\` 형태로 보강됐다. ${hintBody}${reasonBody}`;
  }
  return `검색어는 \`${truncate(effectiveRewritten)}\` 형태로 정리됐다. ${hintBody}${reasonBody}`;
}

function deriveSearchBody(retrievalTrace: Record<string, unknown>): string {
  const metrics = asRecord(retrievalTrace.metrics);
  const ablation = asRecord(retrievalTrace.ablation);
  const bm25Count = Number(asRecord(metrics.bm25).count ?? 0);
  const vectorCount = Number(asRecord(metrics.vector).count ?? 0);
  const hybridCount = Number(asRecord(metrics.hybrid).count ?? 0);
  const topSupport = asString(ablation.top_support) ?? asString(ablation.hybrid_top_support) ?? 'unknown';
  const overlapCount = Number(ablation.bm25_vector_overlap_count ?? 0);

  if (bm25Count <= 0 && vectorCount <= 0 && hybridCount <= 0) {
    return '검색 후보가 아직 잡히지 않아 BM25, Vector, hybrid 전략을 설명할 수 없는 상태다.';
  }
  if (bm25Count > 0 && vectorCount > 0) {
    const lead = (() => {
      if (topSupport === 'vector') {
        return 'BM25와 Vector를 함께 사용했고, Vector 쪽 후보가 더 강했다.';
      }
      if (topSupport === 'bm25') {
        return 'BM25와 Vector를 함께 사용했고, BM25 쪽 후보가 더 강했다.';
      }
      if (topSupport === 'both') {
        return 'BM25와 Vector를 함께 사용했고, 상위 후보는 두 신호를 함께 받았다.';
      }
      return 'BM25와 Vector를 함께 사용해 키워드 일치와 의미 유사도를 동시에 봤다.';
    })();
    const hybridBody = overlapCount > 0
      ? `Hybrid는 두 검색에서 겹친 후보를 정리해 상위 근거를 하나의 순서로 압축했다.`
      : 'Hybrid는 키워드 일치와 의미 유사도를 합쳐 단일 근거 순서를 만들었다.';
    return `${lead} ${hybridBody}`;
  }
  if (vectorCount > 0) {
    return '이번 검색은 Vector 쪽 후보가 중심이었다. 의미적으로 가까운 문서를 먼저 잡아 설명 근거를 세웠다.';
  }
  return '이번 검색은 BM25 쪽 후보가 중심이었다. 질문 표현과 직접 맞닿는 문서를 먼저 끌어와 근거를 세웠다.';
}

function deriveDecisionBody(retrievalTrace: Record<string, unknown>): string {
  const graph = asRecord(retrievalTrace.graph);
  const reranker = asRecord(retrievalTrace.reranker);
  const graphMode = asString(graph.adapter_mode) ?? 'skipped';
  const graphReason = asString(graph.fallback_reason) ?? '';
  const rerankReason = asString(reranker.decision_reason) ?? '';
  const rerankApplied = Boolean(reranker.applied);
  const rerankEnabled = Boolean(reranker.enabled);
  const rerankMode = asString(reranker.mode) ?? 'skipped';
  const rerankTopChanged = Boolean(reranker.top1_changed);
  const rebalanceReasons = uniqueStrings(
    asArray(reranker.rebalance_reasons)
      .map((reason) => asString(reason))
      .filter((reason): reason is string => Boolean(reason))
      .map((reason) => humanizeRerankDecision(reason).replace(/\.$/, '')),
    2,
  );

  const graphBody = (() => {
    if (graphMode === 'skipped') {
      return `graph expand는 생략됐다. ${humanizeGraphReason(graphReason)}`;
    }
    if (graphMode === 'disabled') {
      return 'graph expand는 비활성 상태라 실행되지 않았다.';
    }
    const base = graphMode === 'local_sidecar'
      ? 'graph expand는 local fallback으로 관계를 보강했다.'
      : graphMode === 'neo4j'
        ? 'graph expand는 Neo4j relation graph를 사용해 근거 관계를 보강했다.'
        : graphMode === 'remote_endpoint'
          ? 'graph expand는 remote graph endpoint로 관계를 보강했다.'
          : `graph expand는 ${graphMode} 경로로 관계를 보강했다.`;
    const fallbackBodies = humanizeGraphFallback(graphReason);
    return fallbackBodies.length > 0 ? `${base} ${fallbackBodies.join(' ')}` : base;
  })();

  const rerankBody = (() => {
    if (!rerankEnabled) {
      return 'rerank는 비활성 상태라 적용되지 않았다.';
    }
    if (!rerankApplied) {
      return `rerank는 미적용됐다. ${humanizeRerankDecision(rerankReason)}`;
    }
    const base = rerankMode === 'model'
      ? `rerank는 semantic model을 적용했다. ${humanizeRerankDecision(rerankReason)}`
      : `rerank는 모델 대신 규칙 재정렬만 적용했다. ${humanizeRerankDecision(rerankReason)}`;
    const topBody = rerankTopChanged
      ? '상위 1개 후보는 이 단계에서 다시 정렬됐다.'
      : '상위 1개 후보는 유지됐다.';
    const rebalanceBody = rebalanceReasons.length > 0
      ? `추가 재정렬은 ${rebalanceReasons.join(', ')} 기준을 반영했다.`
      : '';
    return `${base} ${topBody}${rebalanceBody ? ` ${rebalanceBody}` : ''}`;
  })();

  return `${graphBody} ${rerankBody}`.trim();
}

function matchSelectedHit(
  citation: ChatCitation,
  selectedHits: Record<string, unknown>[],
): Record<string, unknown> | null {
  const expectedPath = citation.section_path ?? citation.section;
  return selectedHits.find((hit) => {
    const hitBookSlug = asString(hit.book_slug) ?? '';
    const hitSection = asString(hit.section) ?? '';
    return hitBookSlug === citation.book_slug && hitSection === expectedPath;
  }) ?? null;
}

function deriveCitationReason(
  citation: ChatCitation,
  questionTypeLabel: string,
  selectedHit: Record<string, unknown> | null,
): string {
  const support = (() => {
    if (!selectedHit) {
      return '상위 citation으로 남아 최종 답변에 직접 반영됐다.';
    }
    const hasBm25 = typeof selectedHit.bm25_score === 'number';
    const hasVector = typeof selectedHit.vector_score === 'number';
    if (hasBm25 && hasVector) {
      return 'BM25와 Vector가 함께 지지한 상위 근거였다.';
    }
    if (hasVector) {
      return 'Vector 쪽 의미 검색이 주도한 상위 근거였다.';
    }
    if (hasBm25) {
      return 'BM25 쪽 키워드 일치가 주도한 상위 근거였다.';
    }
    return '최종 선택 단계에서 살아남은 상위 근거였다.';
  })();
  const text = `${citation.book_slug} ${citation.section_path ?? citation.section}`.toLowerCase();
  if (questionTypeLabel === '설명형') {
    if (includesAny(text, ['overview', 'architecture', '개요', '아키텍처', '소개', '정의'])) {
      return `${support} 개념과 구조를 직접 설명하는 섹션이라 답변의 뼈대를 잡았다.`;
    }
    return `${support} 질문의 핵심 개념을 직접 다루는 섹션이라 답변의 중심 근거가 됐다.`;
  }
  if (questionTypeLabel === '비교형') {
    return `${support} 비교 기준이나 차이점을 바로 설명하는 섹션이라 답변의 대비 구성을 지지했다.`;
  }
  if (questionTypeLabel === '절차형') {
    if (includesAny(text, ['절차', '방법', '설치', '구성', '확인', '검증', 'drain', 'backup', 'restore'])) {
      return `${support} 실행 절차나 확인 포인트를 담고 있어 답변의 단계 설명을 지지했다.`;
    }
    return `${support} 절차를 수행할 때 필요한 핵심 단서를 담고 있어 답변의 실행 설명을 지지했다.`;
  }
  return `${support} 질문과 가장 직접적으로 맞닿은 상위 근거라 최종 답변에 크게 기여했다.`;
}

function deriveEvidenceBlock(
  result: ChatResponse | null | undefined,
  questionTypeLabel: string,
): { body: string; items: ExplainEvidenceItem[] } {
  const citations = (result?.citations ?? []).slice(0, 2);
  if (citations.length === 0) {
    return {
      body: '최종 답변은 아직 대표 citation이 확정되지 않았다.',
      items: [],
    };
  }
  const pipelineTrace = asRecord(result?.pipeline_trace);
  const selection = asRecord(pipelineTrace.selection);
  const selectedHits = asArray(selection.selected_hits).map((hit) => asRecord(hit));
  const items = citations.map((citation) => {
    const label = `${citation.book_slug} / ${citation.section_path ?? citation.section}`;
    const selectedHit = matchSelectedHit(citation, selectedHits);
    return {
      label,
      reason: deriveCitationReason(citation, questionTypeLabel, selectedHit),
    };
  });
  const body = `최종 답변은 ${items.map((item) => item.label).join('와 ')}를 중심으로 작성됐다.`;
  return { body, items };
}

export function deriveWorkspaceExplain({
  query,
  result,
}: DeriveWorkspaceExplainInput): WorkspaceExplainModel {
  const retrievalTrace = asRecord(result?.retrieval_trace);
  const plan = asRecord(retrievalTrace.plan);
  const questionType = classifyQuestion(query);
  const rewriteBody = deriveRewriteBody(query, result?.rewritten_query ?? null, plan);
  const searchBody = deriveSearchBody(retrievalTrace);
  const decisionBody = deriveDecisionBody(retrievalTrace);
  const evidence = deriveEvidenceBlock(result, questionType.label);

  return {
    questionTypeLabel: questionType.label,
    questionTypeBody: questionType.body,
    rewriteBody,
    searchBody,
    decisionBody,
    evidenceBody: evidence.body,
    evidenceItems: evidence.items,
    stages: [
      {
        id: 'question-interpretation',
        title: '질문 해석',
        summary: `${questionType.label} 질문으로 보고 검색어를 정리했다.`,
      },
      {
        id: 'evidence-search',
        title: '근거 검색',
        summary: searchBody,
      },
      {
        id: 'answer-decision',
        title: '답변 결정',
        summary: decisionBody,
      },
      {
        id: 'final-evidence',
        title: '최종 근거',
        summary: evidence.body,
      },
    ],
  };
}
