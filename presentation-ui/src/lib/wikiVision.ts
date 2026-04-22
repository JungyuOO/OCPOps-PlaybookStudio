export type VisionMode = 'atlas_canvas' | 'guided_tour' | 'encyclopedia_world';

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
  if (value === 'atlas_canvas' || value === 'guided_tour' || value === 'encyclopedia_world') {
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
      summary: '문서, 관계, figure를 한 화면에서 함께 펼치는 탐험형 위키',
      cue: '문서 중심 + 관계 확장',
    },
    library: {
      eyebrow: 'Document + Relation + Figure',
      summary: '문서 본문을 중심으로 관계 지도와 figure strip을 같이 여는 탐험형 위키입니다.',
      focus: '문서를 읽다가 바로 관계와 도해로 확장',
    },
    compare: {
      title: '읽는 중심형',
      eyebrow: 'Document first',
      bullets: [
        '본문을 먼저 읽고, 옆에서 연결 문서와 절차를 확장합니다.',
        '대표 figure와 관련 문서를 같은 시야 안에 두되 본문 몰입을 해치지 않습니다.',
        '문서를 읽다가 자연스럽게 옆으로 퍼져 나가는 백과 경험을 노립니다.',
      ],
      cta: '이 방식으로 열기',
    },
  },
  {
    id: 'guided_tour',
    label: 'Guided Tour',
    workspace: {
      summary: '질문에서 답으로 끝나지 않고 절차와 다음 문서로 이어지는 투어형 스튜디오',
      cue: '답변 중심 + 다음 단계 안내',
    },
    library: {
      eyebrow: 'Chat-Led Route',
      summary: '챗봇 답변이 문서 투어를 열고 절차, 근거, 다음 문서를 route처럼 안내합니다.',
      focus: '답변이 끝나지 않고 문서 투어로 이어짐',
    },
    compare: {
      title: '행동 유도형',
      eyebrow: 'Action next',
      bullets: [
        '질문에 답하고 끝나지 않고, 다음에 볼 문서와 절차를 바로 제시합니다.',
        '운영자가 지금 무엇을 먼저 해야 하는지 route처럼 안내합니다.',
        '챗봇과 문서가 하나의 업무 흐름으로 이어지는 경험을 노립니다.',
      ],
      cta: '투어 방식으로 열기',
    },
  },
  {
    id: 'encyclopedia_world',
    label: 'Topic World',
    workspace: {
      summary: '책보다 주제 지형도를 먼저 열고 관련 문서를 묶어 탐험하는 대백과 모드',
      cue: '주제 세계 중심 탐색',
    },
    library: {
      eyebrow: 'Encyclopedia Atlas',
      summary: '책 단위보다 주제 세계를 먼저 열고 관련 문서와 그림을 한 번에 탐험하는 구조입니다.',
      focus: '문서보다 주제 지형도를 먼저 보여줌',
    },
    compare: {
      title: '맥락 탐험형',
      eyebrow: 'Context world',
      bullets: [
        '한 문서보다 이 문서가 속한 주제 세계와 연결 고리를 먼저 보여줍니다.',
        '키워드와 연결 문서를 중심으로 큰 그림을 탐험하게 만듭니다.',
        '지식의 지형도를 먼저 보고 필요한 문서를 파고드는 경험을 노립니다.',
      ],
      cta: '맥락 중심으로 열기',
    },
  },
];
