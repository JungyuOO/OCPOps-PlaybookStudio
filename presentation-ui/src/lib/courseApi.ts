import { RUNTIME_ORIGIN, type ChatCitation, type ChatRelatedLink, type ChatResponse } from './runtimeApi';

export interface CourseManifestStage {
  stage_id: string;
  order: number;
  title: string;
  summary_md: string;
  chunk_refs: string[];
  learning_route?: {
    start_here: string[];
    then_open: string[];
    why_this_order: string;
  };
  tour?: {
    stop_refs: string[];
    start_stop_id: string;
    end_stop_id: string;
    stop_count: number;
  };
  review_summary?: {
    approved: number;
    needs_review: number;
  };
  official_route_refs?: Array<Record<string, unknown>>;
}

export interface CourseGuidedCard {
  role: 'start_here' | 'then_open' | 'official_check' | string;
  guide_id?: string;
  step_id?: string;
  chunk_id: string;
  stage_id: string;
  label: string;
  question: string;
  learning_objective?: string;
  viewer_path: string;
  atlas_path: string;
  slide_count: number;
  official_ref_count: number;
  quality?: {
    status?: string;
    needs_review?: string[];
  };
  source?: {
    chunk_id?: string;
    native_id?: string;
    hidden_doc_anchor?: boolean;
  };
}

export interface CourseTourStop {
  stop_id: string;
  chunk_id: string;
  stage_id: string;
  stage_order: number;
  stage_title: string;
  stop_order: number;
  total_stops: number;
  route_role: string;
  title: string;
  native_id: string;
  previous_stop_id: string;
  next_stop_id: string;
  previous_chunk_id: string;
  next_chunk_id: string;
  official_check_count: number;
  atlas_expand_refs?: {
    child_chunk_ids?: string[];
    asset_ids?: string[];
    zone_ids?: string[];
  };
}

export interface CourseManifest {
  canonical_model: string;
  course_slug: string;
  title: string;
  tour?: {
    canonical_model: string;
    entry_stage_id: string;
    entry_stop_id: string;
    stage_count: number;
    stop_count: number;
    stages: Array<Record<string, unknown>>;
    stops: CourseTourStop[];
  };
  stages: CourseManifestStage[];
}

export interface CourseChunkRef {
  chunk_id: string;
  title: string;
  native_id: string;
  variant: string | null;
  review_status?: string;
  slide_count: number;
  slide_refs: Array<Record<string, unknown>>;
  related_official_docs: Array<Record<string, unknown>>;
  beginner_label?: string;
  beginner_question?: string;
  next_question?: string;
  verification_question?: string;
}

export interface CourseImageAttachment {
  asset_id?: string;
  attachment_id?: string;
  source_pptx?: string;
  slide_no?: number;
  shape_index?: number;
  zone_id?: string;
  type?: string;
  kind?: string;
  asset_path?: string;
  ext?: string;
  role?: string;
  bbox_norm?: number[];
  caption_text?: string;
  visual_summary?: string;
  ocr_text?: string;
  searchable?: boolean;
  confidence?: number;
  quality_label?: string;
  instructional_role?: string;
  instructional_roles?: string[];
  state_signal?: string;
  evidence_strength?: number;
  rank_profiles?: Record<string, number>;
  dedupe_group_id?: string;
  duplicate_of_asset_id?: string;
  sha256?: string;
  exclude_from_default?: boolean;
  is_default_visible?: boolean;
  default_visible_order?: number;
  image_rank_order?: number;
}

export interface CourseStagePayload extends CourseManifestStage {
  chunks: CourseChunkRef[];
  guided_cards?: {
    start_here?: CourseGuidedCard[];
    then_open?: CourseGuidedCard[];
    official_check?: CourseGuidedCard[];
  };
}

export interface CourseChunkPayload {
  schema_version?: string;
  canonical_model: string;
  source_kind?: string;
  chunk_id: string;
  stage_id: string;
  title: string;
  native_id: string;
  variant: string | null;
  chunk_kind: string;
  parent_chunk_id: string | null;
  child_chunk_ids: string[];
  review_status?: string;
  review_notes?: string[];
  quality_score?: number;
  body_md: string;
  index_texts?: {
    dense_text?: string;
    sparse_text?: string;
    title_text?: string;
    visual_text?: string;
  };
  structured: Record<string, unknown>;
  slide_refs: Array<Record<string, unknown>>;
  image_attachments: CourseImageAttachment[];
  visual_summary: Record<string, unknown> | null;
  related_official_docs: Array<Record<string, unknown>>;
  source_pptx: string;
  source_slide_range: [number, number];
  tour_stop?: {
    stop_id: string;
    stage_id: string;
    stage_order: number;
    stage_title: string;
    stop_order: number;
    total_stops: number;
    route_role: string;
    previous_stop_id: string;
    next_stop_id: string;
    previous_chunk_id: string;
    next_chunk_id: string;
    official_check_count: number;
    atlas_expand_refs?: {
      child_chunk_ids?: string[];
      asset_ids?: string[];
      zone_ids?: string[];
    };
  };
}

export interface CourseChatSource {
  index: number;
  source_kind: 'project_artifact' | 'official_doc' | string;
  chunk_id: string;
  stage_id: string;
  title: string;
  section_title: string;
  viewer_path: string;
  source_path: string;
}

export interface CourseChatResponse extends ChatResponse {
  lane: string;
  mode: string;
  fallback_used: boolean;
  preview_ready: boolean;
  sources: CourseChatSource[];
  artifacts: Array<Record<string, unknown>>;
  citation_map: Record<string, ChatCitation | CourseChatSource>;
  citations: ChatCitation[];
  related_links?: ChatRelatedLink[];
  related_sections?: ChatRelatedLink[];
}

export type CourseChatStreamEvent =
  | { type: 'stage'; stage?: Record<string, unknown> }
  | { type: 'answer_delta'; delta: string }
  | { type: 'result'; response: CourseChatResponse; payload?: CourseChatResponse }
  | { type: 'error'; error?: string; message?: string };

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${RUNTIME_ORIGIN}${path}`, {
    credentials: 'include',
    ...init,
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { error?: string };
      if (payload.error) {
        message = payload.error;
      }
    } catch {
      // noop
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function loadCourseManifest(): Promise<CourseManifest> {
  return requestJson('/api/v1/course/manifest');
}

export function loadCourseStage(stageId: string): Promise<CourseStagePayload> {
  return requestJson(`/api/v1/course/stages/${encodeURIComponent(stageId)}`);
}

export function loadCourseChunk(chunkId: string): Promise<CourseChunkPayload> {
  return requestJson(`/api/v1/course/chunks/${encodeURIComponent(chunkId)}`);
}

export function searchCourse(query: string, limit = 20): Promise<{ items: CourseChunkRef[]; query: string }> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  return requestJson(`/api/v1/course/search?${params.toString()}`);
}

export function sendCourseChat(payload: {
  message: string;
  sessionId?: string;
  userId?: string;
  stage_id?: string;
  guide_id?: string;
  step_id?: string;
  chunk_ids?: string[];
}): Promise<CourseChatResponse> {
  return requestJson('/api/v1/course/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: payload.message,
        session_id: payload.sessionId,
        user_id: payload.userId,
        stage_id: payload.stage_id,
        guide_id: payload.guide_id,
        step_id: payload.step_id,
        chunk_ids: payload.chunk_ids,
      }),
  });
}

export function emptyCourseChatResponse(answer = ''): CourseChatResponse {
  return {
    lane: 'course',
    mode: 'course',
    fallback_used: false,
    preview_ready: false,
    answer,
    sources: [],
    artifacts: [],
    citation_map: {},
    citations: [],
    related_links: [],
    related_sections: [],
    suggested_queries: [],
    warnings: [],
    session_id: 'course',
    response_kind: 'rag',
  } as CourseChatResponse;
}

export async function sendCourseChatStream(
    payload: {
      message: string;
      sessionId?: string;
      userId?: string;
      stage_id?: string;
      guide_id?: string;
      step_id?: string;
    chunk_ids?: string[];
  },
  onEvent: (event: CourseChatStreamEvent) => void,
): Promise<CourseChatResponse> {
  const response = await fetch(`${RUNTIME_ORIGIN}/api/v1/course/chat/stream`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: payload.message,
      session_id: payload.sessionId,
      user_id: payload.userId,
      stage_id: payload.stage_id,
      guide_id: payload.guide_id,
      step_id: payload.step_id,
      chunk_ids: payload.chunk_ids,
    }),
  });
  if (!response.ok || !response.body) {
    throw new Error(`${response.status} ${response.statusText}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let resultPayload: CourseChatResponse | null = null;

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

    let newlineIndex = buffer.indexOf('\n');
    while (newlineIndex >= 0) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (line) {
        const event = JSON.parse(line) as CourseChatStreamEvent;
        onEvent(event);
        if (event.type === 'error') {
          throw new Error(event.error || event.message || 'stream error');
        }
        if (event.type === 'result') {
          resultPayload = event.response || event.payload || null;
        }
      }
      newlineIndex = buffer.indexOf('\n');
    }

    if (done) {
      break;
    }
  }

  if (buffer.trim()) {
    const event = JSON.parse(buffer.trim()) as CourseChatStreamEvent;
    onEvent(event);
    if (event.type === 'error') {
      throw new Error(event.error || event.message || 'stream error');
    }
    if (event.type === 'result') {
      resultPayload = event.response || event.payload || null;
    }
  }

  if (!resultPayload) {
    throw new Error('stream completed without final result');
  }
  return resultPayload;
}

export function buildCourseAssetUrl(assetPath: string): string {
  return `${RUNTIME_ORIGIN}/api/v1/course/assets?path=${encodeURIComponent(assetPath)}`;
}
