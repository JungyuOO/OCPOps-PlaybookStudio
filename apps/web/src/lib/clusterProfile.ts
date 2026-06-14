import type { OcpConnection } from './opsConsoleApi';

export type ClusterConnectionStatus = 'not_connected' | 'connecting' | 'connected' | 'error';

export const FALLBACK_CLUSTER_USER_LABEL = 'Undefined';

export function normalizeClusterConnectionStatus(connection?: OcpConnection | null): ClusterConnectionStatus {
  const status = connection?.status?.toLowerCase().trim();
  if (!connection || !status || status === 'disconnected' || status === 'not_connected') {
    return 'not_connected';
  }
  if (status === 'connected' || status === 'ready' || status === 'active') {
    return 'connected';
  }
  if (status === 'connecting' || status === 'pending' || status === 'testing') {
    return 'connecting';
  }
  return 'error';
}

export function clusterConnectionStatusLabel(status: ClusterConnectionStatus): string {
  if (status === 'connected') {
    return 'Connected';
  }
  if (status === 'connecting') {
    return 'Connecting';
  }
  if (status === 'error') {
    return 'Error';
  }
  return 'Not connected';
}

export function clusterProfileName(connection?: OcpConnection | null): string {
  const username = connection?.username_hint?.trim();
  const displayName = connection?.display_name?.trim();
  return username || displayName || FALLBACK_CLUSTER_USER_LABEL;
}
