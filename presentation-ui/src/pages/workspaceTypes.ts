import type {
  ChatCitation,
  ChatRelatedLink,
  ChatResponse,
  ChatTraceEvent,
  CustomerPackDraft,
  LibraryBook,
} from '../lib/runtimeApi';

export type WorkspaceManualBook = LibraryBook & {
  library_group?: string;
  library_group_label?: string;
  family?: string;
  family_label?: string;
};

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: ChatCitation[];
  suggestedQueries?: string[];
  relatedLinks?: ChatRelatedLink[];
  relatedSections?: ChatRelatedLink[];
  responseKind?: string;
  acquisition?: {
    kind: string;
    title: string;
    body: string;
    checkbox_label: string;
    confirm_label: string;
    repository_query: string;
  };
  primarySourceLane?: string;
  primaryBoundaryTruth?: string;
  primaryRuntimeTruthLabel?: string;
  primaryBoundaryBadge?: string;
  primaryPublicationState?: string;
  primaryApprovalState?: string;
  rewrittenQuery?: string;
  retrievalTrace?: Record<string, unknown>;
  pipelineTrace?: Record<string, unknown>;
  traceEvents?: ChatTraceEvent[];
}

export interface WorkspaceTestTrace {
  query: string;
  sessionId: string;
  events: ChatTraceEvent[];
  result?: ChatResponse | null;
}

export interface SourceEntry {
  id: string;
  kind: 'manual' | 'draft';
  name: string;
  meta: string;
  grade?: string;
  viewerPath?: string;
  book?: LibraryBook;
  draft?: CustomerPackDraft;
}
