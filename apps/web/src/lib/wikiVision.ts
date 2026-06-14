export type VisionMode = 'atlas_canvas' | 'guided_tour' | 'course_study';

export const DEFAULT_VISION_MODE: VisionMode = 'atlas_canvas';
export const WIKI_VISION_MODE_STORAGE_KEY = 'wikiVisionMode';

export interface VisionCompareCopy {
  title: string;
  eyebrow: string;
  bullets: string[];
  cta: string;
}

export interface WikiVisionModeDescriptor {
  id: VisionMode;
  label: string;
  workspace: {
    summary: string;
    cue: string;
  };
  library: {
    eyebrow: string;
    summary: string;
    focus: string;
  };
  compare: VisionCompareCopy;
}

export function resolveVisionMode(value: string | null | undefined): VisionMode {
  if (value === 'atlas_canvas' || value === 'guided_tour' || value === 'course_study') {
    return value;
  }
  return DEFAULT_VISION_MODE;
}

export function loadStoredVisionMode(): VisionMode {
  if (typeof window === 'undefined') {
    return DEFAULT_VISION_MODE;
  }
  window.localStorage.removeItem(WIKI_VISION_MODE_STORAGE_KEY);
  return DEFAULT_VISION_MODE;
}

export function persistVisionMode(_mode: VisionMode): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.removeItem(WIKI_VISION_MODE_STORAGE_KEY);
}

export const WIKI_VISION_MODES: WikiVisionModeDescriptor[] = [
  {
    id: 'atlas_canvas',
    label: 'Atlas Canvas',
    workspace: {
      summary: '문서 본문을 중심으로 관계, figure, 주석을 한 화면에서 함께 읽는 모드입니다.',
      cue: '문서 중심 + 관계 확장',
    },
    library: {
      eyebrow: 'Document + Relation + Figure',
      summary: '문서 본문을 중심으로 관련 문서와 figure strip을 함께 열어 흐름을 넓힙니다.',
      focus: '문서를 읽다가 바로 근거와 연결 경로로 확장',
    },
    compare: {
      title: '읽는 중심',
      eyebrow: 'Document first',
      bullets: [
        '본문을 먼저 읽고 관련 문서와 절차를 확장합니다.',
        'figure와 관련 문서를 같은 시야에 둡니다.',
        '문서 흐름을 유지하면서 필요한 배경을 함께 확인합니다.',
      ],
      cta: 'Atlas로 열기',
    },
  },
  {
    id: 'guided_tour',
    label: 'Guided Tour',
    workspace: {
      summary: '질문에서 답변으로 끝나지 않고 다음 문서와 절차로 이어지는 채팅 모드입니다.',
      cue: '답변 중심 + 다음 단계 안내',
    },
    library: {
      eyebrow: 'Chat-Led Route',
      summary: '채팅 답변에서 문서 근거, 절차, 다음 문서를 route처럼 안내합니다.',
      focus: '답변을 실행 가능한 다음 경로로 연결',
    },
    compare: {
      title: '행동 유도',
      eyebrow: 'Action next',
      bullets: [
        '질문에 답한 뒤 다음에 볼 문서와 절차를 제시합니다.',
        '운영자가 지금 무엇을 먼저 해야 하는지 안내합니다.',
        '채팅과 문서가 하나의 업무 흐름으로 이어집니다.',
      ],
      cta: 'Tour로 질문',
    },
  },
  {
    id: 'course_study',
    label: '실운영 가이드',
    workspace: {
      summary: '사내 실운영 산출물과 공식 문서를 함께 보여주는 운영 가이드 채팅 모드입니다.',
      cue: '운영 산출물 + 공식 문서 + 다음 단계',
    },
    library: {
      eyebrow: 'Operations Guide',
      summary: 'PPT/PDF 기반 실운영 산출물을 PBS 채팅 UX에서 citation, viewer, guided route와 함께 탐색합니다.',
      focus: '사내 운영 자료를 공식 문서 근거와 함께 학습',
    },
    compare: {
      title: '실운영 가이드',
      eyebrow: 'Operations guide',
      bullets: [
        '사내 PPT/PDF 산출물을 우선 근거로 제시합니다.',
        '연결된 공식 문서를 함께 보여줍니다.',
        '다음 Guided Tour 카드를 추천합니다.',
      ],
      cta: '실운영 가이드로 질문',
    },
  },
];
