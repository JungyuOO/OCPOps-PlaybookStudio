import { ArrowRight, Bot, Check, Copy, Link as LinkIcon, WrapText } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import type { ChatCitation, ChatRelatedLink } from '../../lib/runtimeApi';
import type { VisionMode } from '../../lib/wikiVision';

type TruthSurfacePayload = {
  boundary_truth?: string;
  runtime_truth_label?: string;
  boundary_badge?: string;
  source_lane?: string;
  approval_state?: string;
  publication_state?: string;
  parser_backend?: string;
  pack_label?: string;
} | null | undefined;

type InlineToken =
  | { kind: 'text'; value: string }
  | { kind: 'code'; value: string }
  | { kind: 'strong'; value: string }
  | { kind: 'citation'; index: number; citation?: ChatCitation };

type AnswerBlock =
  | { type: 'paragraph'; parts: InlineToken[] }
  | { type: 'heading'; level: number; parts: InlineToken[] }
  | { type: 'unordered-list'; items: InlineToken[][] }
  | { type: 'step'; number: number; paragraphs: InlineToken[][]; codeBlocks: { code: string; language: string }[] };

export function normalizeRouteKey(link: ChatRelatedLink): string {
  return [
    String(link.kind || '').trim(),
    String(link.href || '').trim(),
    String(link.label || '').trim(),
    String(link.summary || '').trim(),
  ]
    .filter(Boolean)
    .join('::');
}

export function truthSurfaceCopy(payload?: TruthSurfacePayload): {
  label: string;
  meta: string[];
} {
  if (!payload) {
    return { label: '', meta: [] };
  }
  const boundaryTruth = String(payload.boundary_truth || '').trim();
  const sourceLane = String(payload.source_lane || '').trim();
  const runtimeTruthLabel = String(payload.runtime_truth_label || '').trim();
  const packLabel = String(payload.pack_label || '').trim();

  if (boundaryTruth === 'private_customer_pack_runtime' || sourceLane === 'customer_source_first_pack') {
    return {
      label: 'Private Runtime',
      meta: [
        runtimeTruthLabel || 'Customer Source-First Pack',
        payload.approval_state ? `approval ${payload.approval_state}` : '',
        payload.publication_state ? `publication ${payload.publication_state}` : '',
        payload.parser_backend ? `parser ${payload.parser_backend}` : '',
      ].filter(Boolean),
    };
  }

  if (boundaryTruth === 'official_gold_playbook_runtime') {
    return {
      label: 'Gold Playbook',
      meta: [
        runtimeTruthLabel || (packLabel ? `${packLabel} Gold Playbook` : 'Gold Playbook'),
        packLabel || '',
      ].filter(Boolean),
    };
  }

  if (boundaryTruth === 'official_validated_runtime') {
    return {
      label: 'Validated Runtime',
      meta: [
        runtimeTruthLabel || (packLabel ? `${packLabel} Runtime` : 'Validated Pack Runtime'),
        packLabel || '',
      ].filter(Boolean),
    };
  }

  if (boundaryTruth === 'official_candidate_runtime' || sourceLane.includes('candidate')) {
    const isLegacyArchiveLane =
      sourceLane === 'legacy_gold_candidate_archive'
      || sourceLane === 'gold_candidate_archive';
    return {
      label: isLegacyArchiveLane ? 'Archived Runtime' : 'Candidate Runtime',
      meta: [
        runtimeTruthLabel || (packLabel ? `${packLabel} Candidate` : 'Validated Pack Candidate'),
      ].filter(Boolean),
    };
  }

  if (boundaryTruth === 'mixed_runtime_bridge' || sourceLane.includes('mixed')) {
    return {
      label: 'Mixed Runtime',
      meta: [
        runtimeTruthLabel || 'Official + Private Runtime',
      ].filter(Boolean),
    };
  }

  return {
    label: payload.boundary_badge || runtimeTruthLabel || sourceLane || '',
    meta: [
      payload.approval_state ? `approval ${payload.approval_state}` : '',
      payload.publication_state ? `publication ${payload.publication_state}` : '',
      payload.parser_backend ? `parser ${payload.parser_backend}` : '',
    ].filter(Boolean),
  };
}

function formatCitationLabel(citation: ChatCitation): string {
  const base = citation.source_label || citation.book_title || citation.section;
  const truth = truthSurfaceCopy(citation);
  if (truth.label) {
    return `${truth.label} · ${base}`;
  }
  return base;
}

function citationSurfaceCopy(citation: ChatCitation): {
  badge: string;
  title: string;
  meta: string[];
} {
  const truth = truthSurfaceCopy(citation);
  const title = citation.source_label || citation.book_title || citation.section || citation.book_slug;
  const meta = [...truth.meta];
  if (!meta.length && citation.section && citation.section !== title) {
    meta.push(citation.section);
  }
  return {
    badge: truth.label || 'Runtime',
    title,
    meta,
  };
}

function truthBlockCopy(payload?: TruthSurfacePayload): {
  badge: string;
  meta: string[];
} {
  const truth = truthSurfaceCopy(payload);
  return {
    badge: truth.label || 'Runtime',
    meta: truth.meta,
  };
}

export function TruthBadgeBlock({
  payload,
  badgeClassName = 'truth-badge',
  metaClassName = 'truth-meta',
  showMeta = true,
}: {
  payload?: TruthSurfacePayload;
  badgeClassName?: string;
  metaClassName?: string;
  showMeta?: boolean;
}) {
  const truth = truthBlockCopy(payload);
  return (
    <>
      <span className={badgeClassName}>{truth.badge}</span>
      {showMeta && truth.meta.length > 0 && (
        <span className={metaClassName}>{truth.meta.join(' · ')}</span>
      )}
    </>
  );
}

function buildCitationMap(citations: ChatCitation[]): Map<number, ChatCitation> {
  return new Map(citations.map((citation) => [Number(citation.index), citation]));
}

function normalizeAssistantAnswer(text: string): string {
  const stripped = String(text || '').trim().replace(/^답변:\s*/u, '');
  const lines = stripped.split('\n');
  let nextStep = 1;
  return lines
    .map((line) => {
      const match = line.match(/^(\s*)(\d+)\.\s+(.*)$/);
      if (!match || match[1].length > 0) {
        return line;
      }
      return `${match[1]}${nextStep++}. ${match[3]}`;
    })
    .join('\n');
}

function parseInlineTokens(text: string, citationsByIndex: Map<number, ChatCitation>): InlineToken[] {
  const chunks = String(text || '').split(/(`[^`]+`|\*\*[^*]+\*\*|\[\d+\])/g);
  const tokens: InlineToken[] = [];
  chunks.forEach((chunk) => {
    if (!chunk) {
      return;
    }
    if (chunk.startsWith('`') && chunk.endsWith('`') && chunk.length >= 2) {
      tokens.push({ kind: 'code', value: chunk.slice(1, -1) });
      return;
    }
    if (chunk.startsWith('**') && chunk.endsWith('**') && chunk.length >= 4) {
      tokens.push({ kind: 'strong', value: chunk.slice(2, -2) });
      return;
    }
    const citationMatch = chunk.match(/^\[(\d+)\]$/);
    if (citationMatch) {
      const index = Number(citationMatch[1]);
      tokens.push({
        kind: 'citation',
        index,
        citation: citationsByIndex.get(index),
      });
      return;
    }
    tokens.push({ kind: 'text', value: chunk });
  });
  return tokens;
}

function parseAnswerBlocks(text: string, citations: ChatCitation[]): AnswerBlock[] {
  const normalized = normalizeAssistantAnswer(text).replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const citationsByIndex = buildCitationMap(citations);
  const lines = normalized.split('\n');
  const blocks: AnswerBlock[] = [];

  let currentStep: Extract<AnswerBlock, { type: 'step' }> | null = null;
  let stepBuffer: string[] = [];
  let paragraphBuffer: string[] = [];
  let listBuffer: InlineToken[][] = [];
  let inCode = false;
  let codeLanguage = '';
  let codeLines: string[] = [];

  const flushParagraph = (): void => {
    if (!paragraphBuffer.length) {
      return;
    }
    const textValue = paragraphBuffer.join('\n').trim();
    if (textValue) {
      blocks.push({ type: 'paragraph', parts: parseInlineTokens(textValue, citationsByIndex) });
    }
    paragraphBuffer = [];
  };

  const flushList = (): void => {
    if (!listBuffer.length) {
      return;
    }
    blocks.push({ type: 'unordered-list', items: [...listBuffer] });
    listBuffer = [];
  };

  const flushStepParagraph = (): void => {
    if (!currentStep || !stepBuffer.length) {
      return;
    }
    const textValue = stepBuffer.join('\n').trim();
    if (textValue) {
      currentStep.paragraphs.push(parseInlineTokens(textValue, citationsByIndex));
    }
    stepBuffer = [];
  };

  const flushStep = (): void => {
    if (!currentStep) {
      return;
    }
    flushStepParagraph();
    blocks.push(currentStep);
    currentStep = null;
  };

  const flushCode = (): void => {
    const code = codeLines.join('\n').trimEnd();
    if (!code) {
      codeLines = [];
      codeLanguage = '';
      return;
    }
    if (currentStep) {
      flushStepParagraph();
      currentStep.codeBlocks.push({ code, language: codeLanguage || 'text' });
    } else {
      blocks.push({
        type: 'paragraph',
        parts: [{ kind: 'code', value: code }],
      });
    }
    codeLines = [];
    codeLanguage = '';
  };

  lines.forEach((line) => {
    const fence = line.match(/^```([\w.+-]*)\s*$/);
    if (fence) {
      if (inCode) {
        flushCode();
        inCode = false;
      } else {
        flushParagraph();
        flushList();
        codeLanguage = fence[1] || 'text';
        inCode = true;
      }
      return;
    }

    if (inCode) {
      codeLines.push(line);
      return;
    }

    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      flushList();
      flushStepParagraph();
      return;
    }

    const headingMatch = trimmed.match(/^(#{1,3})\s+(.*)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      flushStep();
      blocks.push({
        type: 'heading',
        level: headingMatch[1].length,
        parts: parseInlineTokens(headingMatch[2], citationsByIndex),
      });
      return;
    }

    const orderedMatch = trimmed.match(/^(\d+)\.\s+(.*)$/);
    if (orderedMatch) {
      flushParagraph();
      flushList();
      flushStep();
      currentStep = {
        type: 'step',
        number: Number(orderedMatch[1]),
        paragraphs: [],
        codeBlocks: [],
      };
      stepBuffer.push(orderedMatch[2]);
      return;
    }

    const unorderedMatch = trimmed.match(/^[-*]\s+(.*)$/);
    if (unorderedMatch && !currentStep) {
      flushParagraph();
      listBuffer.push(parseInlineTokens(unorderedMatch[1], citationsByIndex));
      return;
    }

    if (currentStep) {
      stepBuffer.push(trimmed);
      return;
    }

    paragraphBuffer.push(trimmed);
  });

  flushParagraph();
  flushList();
  flushStep();

  if (blocks.length === 0 && normalized.trim()) {
    blocks.push({
      type: 'paragraph',
      parts: parseInlineTokens(normalized.trim(), citationsByIndex),
    });
  }

  return blocks;
}

function InlineParts({
  parts,
  onCitationClick,
}: {
  parts: InlineToken[];
  onCitationClick: (citation: ChatCitation) => void;
}) {
  return (
    <>
      {parts.map((part, index) => {
        if (part.kind === 'code') {
          return <code key={`code-${index}`} className="inline-code">{part.value}</code>;
        }
        if (part.kind === 'strong') {
          return <strong key={`strong-${index}`}>{part.value}</strong>;
        }
        if (part.kind === 'citation' && part.citation) {
          const citation = part.citation;
          return (
            <button
              key={`citation-${index}`}
              type="button"
              className="inline-citation"
              onClick={() => onCitationClick(citation)}
            >
              {part.index}
            </button>
          );
        }
        if (part.kind === 'citation') {
          return <span key={`citation-text-${index}`}>[{part.index}]</span>;
        }
        return <span key={`text-${index}`}>{part.value}</span>;
      })}
    </>
  );
}

function AnswerCodeBlock({ code, language }: { code: string; language: string }) {
  const [wrapped, setWrapped] = useState(false);
  const [copied, setCopied] = useState(false);
  const segments = useMemo(() => {
    const lines = code.split('\n');
    const parsed: Array<{ type: 'note' | 'code'; value: string }> = [];
    let noteBuffer: string[] = [];
    let codeBuffer: string[] = [];

    const flushNotes = () => {
      const text = noteBuffer
        .map((line) => line.replace(/^#\s?/, '').trim())
        .filter(Boolean)
        .join(' ');
      if (text) {
        parsed.push({ type: 'note', value: text });
      }
      noteBuffer = [];
    };

    const flushCode = () => {
      const text = codeBuffer.join('\n').trim();
      if (text) {
        parsed.push({ type: 'code', value: text });
      }
      codeBuffer = [];
    };

    lines.forEach((line) => {
      const trimmed = line.trim();
      if (!trimmed) {
        flushNotes();
        flushCode();
        return;
      }
      if (trimmed.startsWith('#')) {
        flushCode();
        noteBuffer.push(trimmed);
        return;
      }
      flushNotes();
      codeBuffer.push(line);
    });

    flushNotes();
    flushCode();

    return parsed.length > 0 ? parsed : [{ type: 'code', value: code.trim() }];
  }, [code]);

  async function handleCopy(): Promise<void> {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(code);
      } else {
        const helper = document.createElement('textarea');
        helper.value = code;
        helper.setAttribute('readonly', 'true');
        helper.style.position = 'fixed';
        helper.style.opacity = '0';
        document.body.appendChild(helper);
        helper.select();
        document.execCommand('copy');
        document.body.removeChild(helper);
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section className={`answer-code-block ${wrapped ? 'is-wrapped' : ''}`}>
      <div className="answer-code-header">
        <span className="answer-code-lang">{(language || 'text').toUpperCase()}</span>
        <div className="answer-code-actions">
          <button type="button" className="answer-code-action" onClick={() => { void handleCopy(); }} title={copied ? '복사됨' : '복사'}>
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </button>
          <button type="button" className={`answer-code-action ${wrapped ? 'active' : ''}`} onClick={() => setWrapped((value) => !value)} title={wrapped ? '줄바꿈 해제' : '줄바꿈'}>
            <WrapText size={14} />
          </button>
        </div>
      </div>
      <div className="answer-code-body">
        {segments.map((segment, index) => (
          segment.type === 'note' ? (
            <p key={`note-${index}`} className="answer-code-note">{segment.value}</p>
          ) : (
            <pre key={`code-${index}`} className="answer-code-pre"><code>{segment.value}</code></pre>
          )
        ))}
      </div>
    </section>
  );
}

export function ThinkingIndicator() {
  return (
    <div className="message-row assistant animate-in">
      <div className="message-bubble glass-panel thinking-bubble">
        <div className="assistant-head thinking-head">
          <div className="assistant-avatar small">
            <Bot size={14} />
          </div>
          <div className="typing-indicator-dots">
            <div className="typing-dot"></div>
            <div className="typing-dot"></div>
            <div className="typing-dot"></div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function AssistantAnswer({
  content,
  citations,
  relatedLinks,
  relatedSections,
  visionMode,
  primarySourceLane,
  primaryBoundaryTruth,
  primaryRuntimeTruthLabel,
  primaryBoundaryBadge,
  primaryPublicationState,
  primaryApprovalState,
  onCitationClick,
  onRelatedLinkClick,
  onToggleFavoriteLink,
  onCheckSectionLink,
  isFavoriteLink,
  isCheckedSectionLink,
}: {
  content: string;
  citations: ChatCitation[];
  relatedLinks: ChatRelatedLink[];
  relatedSections: ChatRelatedLink[];
  visionMode: VisionMode;
  primarySourceLane?: string;
  primaryBoundaryTruth?: string;
  primaryRuntimeTruthLabel?: string;
  primaryBoundaryBadge?: string;
  primaryPublicationState?: string;
  primaryApprovalState?: string;
  onCitationClick: (citation: ChatCitation) => void;
  onRelatedLinkClick: (link: ChatRelatedLink) => void;
  onToggleFavoriteLink: (link: ChatRelatedLink) => void;
  onCheckSectionLink: (link: ChatRelatedLink) => void;
  isFavoriteLink: (link: ChatRelatedLink) => boolean;
  isCheckedSectionLink: (link: ChatRelatedLink) => boolean;
}) {
  const [displayLength, setDisplayLength] = useState(0);

  useEffect(() => {
    if (displayLength > 0) {
      const chatContainer = document.querySelector('.chat-messages');
      if (chatContainer && !chatContainer.classList.contains('scroll-locked')) {
        requestAnimationFrame(() => {
          chatContainer.scrollTo({
            top: chatContainer.scrollHeight,
            behavior: 'auto',
          });
        });
      }
    }
  }, [displayLength]);

  useEffect(() => {
    if (displayLength < content.length) {
      const timer = setTimeout(() => {
        setDisplayLength((prev) => Math.min(prev + 3, content.length));
      }, 15);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [displayLength, content]);

  const displayedContent = content.slice(0, displayLength);
  const blocks = useMemo(() => parseAnswerBlocks(displayedContent, citations), [displayedContent, citations]);
  const isGuidedTour = visionMode === 'guided_tour';
  const guidedTourSteps = useMemo(() => {
    const unique: ChatRelatedLink[] = [];
    const seen = new Set<string>();
    for (const link of relatedSections) {
      const key = normalizeRouteKey(link);
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      unique.push(link);
      if (unique.length >= 2) {
        break;
      }
    }
    return unique;
  }, [relatedSections]);
  const guidedTourDocs = useMemo(() => {
    const unique: ChatRelatedLink[] = [];
    const seen = new Set<string>(guidedTourSteps.map((link) => normalizeRouteKey(link)));
    for (const link of relatedLinks) {
      const key = normalizeRouteKey(link);
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      unique.push(link);
      if (unique.length >= 2) {
        break;
      }
    }
    return unique;
  }, [guidedTourSteps, relatedLinks]);
  const hasGuidedTour = isGuidedTour && (guidedTourSteps.length > 0 || guidedTourDocs.length > 0);
  const guidedTourLead = useMemo(() => {
    if (!hasGuidedTour) {
      return null;
    }
    const firstStep = guidedTourSteps[0];
    const secondStep = guidedTourSteps[1];
    const firstDoc = guidedTourDocs[0];
    return {
      start: firstStep?.label,
      then: secondStep?.label ?? firstDoc?.label,
      why: firstDoc?.summary ?? secondStep?.summary ?? firstStep?.summary,
    };
  }, [guidedTourDocs, guidedTourSteps, hasGuidedTour]);
  const hasTruth = Boolean(
    primaryBoundaryTruth ||
    primarySourceLane ||
    primaryRuntimeTruthLabel ||
    primaryBoundaryBadge,
  );

  return (
    <div className="assistant-answer">
      <div className="assistant-head">
        <div className="assistant-avatar">
          <Bot size={18} />
        </div>
        <div className="assistant-head-copy">
          <span className="assistant-label">Playbot</span>
          {hasTruth && (
            <div className="assistant-truth-row">
              <TruthBadgeBlock
                payload={{
                  boundary_truth: primaryBoundaryTruth,
                  runtime_truth_label: primaryRuntimeTruthLabel,
                  boundary_badge: primaryBoundaryBadge,
                  source_lane: primarySourceLane,
                  approval_state: primaryApprovalState,
                  publication_state: primaryPublicationState,
                }}
                badgeClassName="assistant-truth-chip"
                metaClassName="assistant-truth-meta"
                showMeta={false}
              />
            </div>
          )}
        </div>
      </div>
      {guidedTourLead && (
        <div className="guided-tour-lead">
          <div className="guided-tour-lead-kicker">Route First</div>
          <div className="guided-tour-lead-title">
            {guidedTourLead.start ? `${guidedTourLead.start}부터 여세요.` : '이 경로부터 따라가면 됩니다.'}
          </div>
          {guidedTourLead.then && (
            <p className="guided-tour-lead-copy">
              이어서 <strong>{guidedTourLead.then}</strong>로 이동합니다.
            </p>
          )}
          {guidedTourLead.why && (
            <p className="guided-tour-lead-copy subdued">{guidedTourLead.why}</p>
          )}
        </div>
      )}
      <div className="assistant-copy">
        {blocks.map((block, index) => {
          if (block.type === 'heading') {
            const Tag = block.level === 1 ? 'h2' : 'h3';
            return (
              <Tag key={`heading-${index}`} className="assistant-heading">
                <InlineParts parts={block.parts} onCitationClick={onCitationClick} />
              </Tag>
            );
          }
          if (block.type === 'unordered-list') {
            return (
              <ul key={`unordered-${index}`} className="assistant-list">
                {block.items.map((item, itemIndex) => (
                  <li key={`unordered-item-${itemIndex}`} className="assistant-list-item">
                    <InlineParts parts={item} onCitationClick={onCitationClick} />
                  </li>
                ))}
              </ul>
            );
          }
          if (block.type === 'step') {
            return (
              <div key={`step-${index}`} className="assistant-step">
                <div className="assistant-step-badge">{block.number}</div>
                <div className="assistant-step-body">
                  {block.paragraphs.map((paragraph, paragraphIndex) => (
                    <p key={`step-paragraph-${paragraphIndex}`} className="assistant-step-paragraph">
                      <InlineParts parts={paragraph} onCitationClick={onCitationClick} />
                    </p>
                  ))}
                  {block.codeBlocks.map((codeBlock, codeIndex) => (
                    <AnswerCodeBlock
                      key={`step-code-${codeIndex}`}
                      code={codeBlock.code}
                      language={codeBlock.language}
                    />
                  ))}
                </div>
              </div>
            );
          }
          const paragraphClasses = ['assistant-paragraph'];
          if (index === 0) {
            paragraphClasses.push('assistant-lead');
          }
          const singleCodePart = block.parts.length === 1 && block.parts[0]?.kind === 'code'
            ? block.parts[0]
            : null;
          if (singleCodePart) {
            return (
              <AnswerCodeBlock
                key={`code-only-${index}`}
                code={singleCodePart.value}
                language="text"
              />
            );
          }
          return (
            <p key={`paragraph-${index}`} className={paragraphClasses.join(' ')}>
              <InlineParts parts={block.parts} onCitationClick={onCitationClick} />
            </p>
          );
        })}
      </div>
      {hasGuidedTour && (
        <div className="guided-tour-group">
          <div className="suggested-query-label">Guided Tour</div>
          <div className="guided-tour-header">
            <div>
              <div className="guided-tour-title">이 순서로 따라가면 됩니다</div>
              <p className="guided-tour-summary">
                핵심 절차 {guidedTourSteps.length}개와 관련 문서 {guidedTourDocs.length}개만 먼저 엽니다.
              </p>
            </div>
          </div>
          <div className="guided-tour-route">
            {guidedTourSteps.length > 0 && (
              <div className="guided-tour-lane">
                <div className="guided-tour-lane-label">Start Here</div>
                {guidedTourSteps.map((link, index) => (
                  <button
                    key={`guided-step-${link.href}-${index}`}
                    className="guided-tour-card guided-tour-card-step"
                    type="button"
                    onClick={() => onRelatedLinkClick(link)}
                    title={link.summary ?? ''}
                  >
                    <span className="guided-tour-kicker">Step {index + 1}</span>
                    <strong>{link.label}</strong>
                    <span>{link.summary || '지금 바로 확인해야 할 절차입니다.'}</span>
                  </button>
                ))}
              </div>
            )}
            {guidedTourDocs.length > 0 && (
              <div className="guided-tour-lane">
                <div className="guided-tour-lane-label">Then Open</div>
                {guidedTourDocs.map((link, index) => (
                  <button
                    key={`guided-doc-${link.href}-${index}`}
                    className="guided-tour-card guided-tour-card-doc"
                    type="button"
                    onClick={() => onRelatedLinkClick(link)}
                    title={link.summary ?? ''}
                  >
                    <span className="guided-tour-kicker">Document {index + 1}</span>
                    <strong>{link.label}</strong>
                    <span>{link.summary || '이 절차를 따라간 뒤 이어서 참고할 문서입니다.'}</span>
                    <span className="guided-tour-arrow">
                      <ArrowRight size={14} />
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
      {!isGuidedTour && relatedLinks.length > 0 && (
        <div className="assistant-related-group">
          <div className="suggested-query-label">관련 문서</div>
          <div className="suggested-query-list">
            {relatedLinks.map((link, index) => (
              <div key={`${link.href}-${index}`} className="overlay-chip-row">
                <RelatedLinkCard link={link} onOpen={onRelatedLinkClick} />
                <button
                  type="button"
                  className={`overlay-mini-action ${isFavoriteLink(link) ? 'active' : ''}`}
                  onClick={() => onToggleFavoriteLink(link)}
                  title={isFavoriteLink(link) ? '즐겨찾기 해제' : '즐겨찾기'}
                >
                  <Check size={12} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
      {!isGuidedTour && relatedSections.length > 0 && (
        <div className="assistant-related-group">
          <div className="suggested-query-label">바로 볼 절차</div>
          <div className="suggested-query-list">
            {relatedSections.map((link, index) => (
              <div key={`${link.href}-${index}`} className="overlay-chip-row">
                <button
                  className="suggested-query-chip"
                  type="button"
                  onClick={() => onRelatedLinkClick(link)}
                  title={link.summary ?? ''}
                >
                  섹션 · {link.label}
                </button>
                <button
                  type="button"
                  className={`overlay-mini-action ${isCheckedSectionLink(link) ? 'active' : ''}`}
                  onClick={() => onCheckSectionLink(link)}
                  title={isCheckedSectionLink(link) ? '체크 해제' : '체크 완료'}
                >
                  <Check size={12} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function CitationTag({
  citation,
  onOpen,
}: {
  citation: ChatCitation;
  onOpen: (citation: ChatCitation) => void;
}) {
  const surface = citationSurfaceCopy(citation);
  return (
    <button
      className="citation-tag"
      onClick={() => { onOpen(citation); }}
      type="button"
      title={formatCitationLabel(citation)}
    >
      <div className="citation-tag-topline">
        <span className="citation-tag-badge">{surface.badge}</span>
        <span className="citation-tag-link">
          <LinkIcon size={12} />
        </span>
      </div>
      <div className="citation-tag-title">{surface.title}</div>
      {surface.meta.length > 0 && (
        <div className="citation-tag-meta">{surface.meta.join(' · ')}</div>
      )}
    </button>
  );
}

export function RelatedLinkCard({
  link,
  onOpen,
}: {
  link: ChatRelatedLink;
  onOpen: (link: ChatRelatedLink) => void;
}) {
  const truth = truthBlockCopy(link);
  const meta = link.summary ? [link.summary] : [];
  return (
    <button
      className="related-link-card"
      type="button"
      onClick={() => onOpen(link)}
    >
      <div className="related-link-topline">
        <span className="related-link-badge">{link.kind === 'entity' ? 'Entity' : truth.badge}</span>
        <span className="related-link-link">
          <LinkIcon size={12} />
        </span>
      </div>
      <div className="related-link-title">{link.label}</div>
      {link.kind !== 'entity' && meta.length > 0 && (
        <div className="related-link-meta">{meta.join(' · ')}</div>
      )}
    </button>
  );
}
