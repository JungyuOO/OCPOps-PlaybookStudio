export const ROUTES = {
  sharedHome: '/',
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
} as const;

export const RESERVED_PBS_PATH_PREFIXES = [
  ROUTES.pbsPlaybookLibrary,
  ROUTES.pbsStudio,
  ROUTES.pbsWikiBook,
] as const;

export function buildSharedLandingHref(): string {
  return ROUTES.sharedHome;
}
