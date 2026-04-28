export const ROUTES = {
  sharedHome: '/',
  pbsDetails: '/details',
  pbsStudio: '/studio',
  pbsWorkspaceAlias: '/workspace',
  pbsWikiBook: '/llmwikibook',
  pbsWikiBookAlias: '/studio-v2',
  pbsPlaybookLibrary: '/playbook-library',
  pbsControlTower: '/playbook-library/control-tower',
  pbsRepository: '/playbook-library/repository',
  courseHome: '/course',
  courseStage: (stageId: string) => `/course/stages/${stageId}`,
  courseChunk: (chunkId: string) => `/course/chunks/${chunkId}`,
  courseAtlas: (chunkId: string) => `/course/atlas/${chunkId}`,
  opsWorkspaces: '/workspaces',
  opsConnections: '/connections',
  opsOverview: '/overview',
  opsResources: '/resources',
  opsLibrary: '/library',
  opsChat: '/chat',
  opsActions: '/actions',
  opsScm: '/scm',
  partnerHome: '/partner',
  partnerWorkspace: '/partner/workspace',
  partnerLibrary: '/partner/library',
  partnerViewer: '/partner/viewer',
  partnerDetails: '/partner/details',
} as const;

export type SharedLandingTab = 'pbs' | 'partner';

export const RESERVED_PBS_PATH_PREFIXES = [
  ROUTES.pbsPlaybookLibrary,
  ROUTES.pbsStudio,
  ROUTES.pbsWikiBook,
] as const;

export const PARTNER_NAMESPACE_PATHS = [
  ROUTES.partnerHome,
  ROUTES.partnerWorkspace,
  ROUTES.partnerLibrary,
  ROUTES.partnerViewer,
  ROUTES.partnerDetails,
] as const;

export function normalizeSharedLandingTab(value: string | null | undefined): SharedLandingTab {
  return value === 'partner' ? 'partner' : 'pbs';
}

export function buildSharedLandingHref(tab: SharedLandingTab = 'pbs'): string {
  return tab === 'pbs' ? ROUTES.sharedHome : `${ROUTES.sharedHome}?tab=${tab}`;
}
