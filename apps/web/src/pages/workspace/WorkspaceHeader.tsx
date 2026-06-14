import AppHeader from '../../components/AppHeader';
import type { ClusterConnectionStatus } from '../../lib/clusterProfile';

type WorkspaceHeaderProps = {
  globalTheme: 'dark' | 'light';
  onOpenDashboard: () => void;
  onOpenLibrary: () => void;
  onToggleGlobalTheme: () => void;
  profileName: string;
  profileStatus: ClusterConnectionStatus;
  profileStatusLabel: string;
  isProfileLoading?: boolean;
};

export default function WorkspaceHeader({
  onOpenDashboard,
  onOpenLibrary,
  onToggleGlobalTheme,
  globalTheme,
  profileName,
  profileStatus,
  profileStatusLabel,
  isProfileLoading,
}: WorkspaceHeaderProps) {
  return (
    <AppHeader
      currentPage="studio"
      globalTheme={globalTheme}
      onOpenDashboard={onOpenDashboard}
      onOpenLibrary={onOpenLibrary}
      onToggleGlobalTheme={onToggleGlobalTheme}
      profile={{
        name: profileName,
        status: profileStatus,
        statusLabel: profileStatusLabel,
        isLoading: isProfileLoading,
        onClick: onOpenDashboard,
      }}
    />
  );
}
