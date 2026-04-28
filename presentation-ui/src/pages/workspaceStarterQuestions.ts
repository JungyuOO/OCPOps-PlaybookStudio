export type WorkspaceChatMode = 'learn' | 'ops';

export const OPS_STARTER_QUESTION_POOL = [
  '운영 입문 기준으로 먼저 봐야 할 플레이북 3개 알려줘',
  'Operator 장애가 났을 때 monitoring과 operators 문서를 어떤 순서로 확인해야 하나?',
  '클러스터 네트워크 MTU 변경 전후에 어떤 절차와 검증을 확인해야 하나?',
  '인증 문제와 Ingress 노출 문제를 같이 볼 때 어떤 책 순서로 확인해야 하나?',
  '연결이 끊긴 환경에서 미러 레지스트리 설정을 점검할 때 운영자가 먼저 볼 문서는 무엇인가?',
  '특정 namespace에 admin 권한을 주려면 어떤 절차를 먼저 확인해야 하나?',
  '프로젝트가 Terminating에서 안 지워질 때 어떤 순서로 확인해야 하나?',
  '노드가 Ready가 아니거나 머신컨피그 적용이 늦을 때 어디부터 상태를 확인해야 하나?',
  'Route나 Ingress 연결 문제를 점검할 때 먼저 볼 절차를 알려줘',
  '모니터링 알림이 쏟아질 때 운영자가 먼저 확인할 플레이북 순서를 알려줘',
  '클러스터 설치 후 Day-2 운영에서 먼저 읽어야 할 문서를 순서대로 알려줘',
  '인증서 갱신이나 만료 문제를 볼 때 먼저 확인할 책과 절차를 알려줘',
];

export const LEARN_STARTER_QUESTION_POOL = [
  'OpenShift를 처음 배우는 사람에게 개요, 아키텍처, Operator를 어떤 순서로 설명하면 좋을까?',
  'Kubernetes와 OpenShift의 차이를 공식 문서 근거로 개념 중심으로 설명해줘',
  'Pod가 생성되고 실행되기까지 어떤 컴포넌트가 관여하는지 학습 순서로 설명해줘',
  'Operator가 왜 필요한지 개념, 구성 요소, 운영자가 알아야 할 경계로 나눠 설명해줘',
  'Route와 Ingress의 개념 차이를 초보자가 헷갈리지 않게 비교해서 설명해줘',
  'MachineConfig와 노드 업데이트 흐름을 학습자 관점에서 단계별로 설명해줘',
  'OpenShift 인증과 RBAC를 처음 공부할 때 꼭 구분해야 할 개념을 알려줘',
  '모니터링, 로깅, 관찰성 문서를 어떤 순서로 읽으면 전체 그림이 잡히는지 알려줘',
  '스토리지와 백업/복구를 배우기 전에 먼저 알아야 할 OCP 개념을 정리해줘',
  'Disconnected 환경을 이해하려면 이미지, 레지스트리, 네트워크를 어떤 순서로 봐야 해?',
  '공식 문서와 고객 PPT를 같이 읽을 때 학습 경로를 어떻게 나누면 좋을까?',
  'Day-1 설치 지식과 Day-2 운영 지식을 어떻게 이어서 학습하면 좋을까?',
];

export function starterQuestionPoolForMode(mode: WorkspaceChatMode): string[] {
  return mode === 'learn' ? LEARN_STARTER_QUESTION_POOL : OPS_STARTER_QUESTION_POOL;
}
