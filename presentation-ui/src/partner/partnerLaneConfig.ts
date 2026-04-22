import { Boxes, FolderTree, MonitorPlay, type LucideIcon } from 'lucide-react';
import { ROUTES } from '../app/routes';

export type PartnerRouteDefinition = {
  path: string;
  eyebrow: string;
  title: string;
  description: string;
  card?: {
    icon: LucideIcon;
    title: string;
    description: string;
  };
};

export const PARTNER_ROUTE_DEFINITIONS: PartnerRouteDefinition[] = [
  {
    path: ROUTES.partnerHome,
    eyebrow: 'Partner Lane',
    title: 'Reserved partner namespace',
    description: '다른 프로젝트 기능은 PBS route family를 침범하지 않고 sibling namespace 아래에서 병합됩니다.',
    card: {
      icon: Boxes,
      title: 'Partner Home',
      description: '공유 랜딩에서 시작되는 상대 프로젝트 메인 진입면',
    },
  },
  {
    path: ROUTES.partnerWorkspace,
    eyebrow: 'Partner Workspace',
    title: 'Partner workspace handoff',
    description: '상대 프로젝트의 작업 공간은 이 sibling namespace로 유입되고, PBS workspace state와 분리됩니다.',
  },
  {
    path: ROUTES.partnerLibrary,
    eyebrow: 'Partner Library',
    title: 'Partner library reservation',
    description: '상대 프로젝트 library 진입면은 이 경로에 들어오고, PBS Playbook Library와 canonical truth를 공유하지 않습니다.',
    card: {
      icon: FolderTree,
      title: 'Partner Library',
      description: 'PBS Playbook Library와 분리된 sibling library namespace',
    },
  },
  {
    path: ROUTES.partnerViewer,
    eyebrow: 'Partner Viewer',
    title: 'Partner viewer reservation',
    description: '상대 프로젝트 viewer는 reserved namespace로 분리되며, PBS wiki runtime viewer deep link와 충돌하지 않습니다.',
    card: {
      icon: MonitorPlay,
      title: 'Partner Viewer',
      description: 'PBS wiki runtime deep link와 충돌하지 않는 reserved viewer lane',
    },
  },
  {
    path: ROUTES.partnerDetails,
    eyebrow: 'Partner Details',
    title: 'Partner details placeholder',
    description: '공유 랜딩은 여기로 handoff할 수 있지만, 제품 소개와 runtime truth ownership은 PBS 바깥 sibling lane에 남습니다.',
  },
];

export const PARTNER_SURFACES = PARTNER_ROUTE_DEFINITIONS.filter(
  (route): route is PartnerRouteDefinition & { card: NonNullable<PartnerRouteDefinition['card']> } => Boolean(route.card),
);
