import { Cpu, FileText, LayoutDashboard, Library, Menu, Monitor, Sparkles } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { GlobalTheme } from '../lib/globalTheme';
import type { ClusterConnectionStatus } from '../lib/clusterProfile';
import { buildSharedLandingHref, ROUTES } from '../routing/routes';
import ThemeToggleButton from './ThemeToggleButton';
import './AppHeader.css';

type AppHeaderPage = 'studio' | 'library' | 'landing';

type AppHeaderProfile = {
  name: string;
  status: ClusterConnectionStatus;
  statusLabel: string;
  isLoading?: boolean;
  onClick?: () => void;
};

type AppHeaderProps = {
  currentPage: AppHeaderPage;
  globalTheme: GlobalTheme;
  onToggleGlobalTheme: () => void;
  onOpenDashboard?: () => void;
  onOpenLibrary?: () => void;
  onOpenStudio?: () => void;
  profile?: AppHeaderProfile;
  title?: string;
};

export default function AppHeader({
  currentPage,
  globalTheme,
  onToggleGlobalTheme,
  onOpenDashboard,
  onOpenLibrary,
  onOpenStudio,
  profile,
  title,
}: AppHeaderProps) {
  const productTitle = title || (currentPage === 'library' ? 'WIKI Library' : 'Playbook Studio');

  return (
    <header className="app-header">
      <div className="app-header-left">
        <Link to={buildSharedLandingHref()} className="app-header-logo-link" aria-label="Playbook Studio home">
          <span className="app-header-logo">
            <Sparkles size={19} />
          </span>
        </Link>
        <div className="app-header-title">
          <strong>{productTitle}</strong>
        </div>
      </div>

      <div className="app-header-right">
        {profile ? (
          <button
            type="button"
            className={`app-header-profile app-header-profile--${profile.status}`}
            onClick={profile.onClick}
            disabled={!profile.onClick}
            title={profile.statusLabel}
          >
            <span className="app-header-profile-icon">
              <Cpu size={15} />
              <span className="app-header-profile-dot" />
            </span>
            <span className="app-header-profile-copy">
              <strong>{profile.isLoading ? 'Syncing' : profile.name}</strong>
              <small>{profile.statusLabel}</small>
            </span>
          </button>
        ) : null}

        <details className="app-header-menu">
          <summary className="app-header-menu-trigger" aria-label="Workspace menu" title="Workspace menu">
            <Menu size={18} />
          </summary>
          <div className="app-header-menu-panel">
            {onOpenDashboard ? (
              <button type="button" className="app-header-menu-item" onClick={onOpenDashboard}>
                <LayoutDashboard size={15} />
                <span>Dashboard</span>
              </button>
            ) : (
              <Link className="app-header-menu-item" to={ROUTES.pbsControlTower}>
                <LayoutDashboard size={15} />
                <span>Dashboard</span>
              </Link>
            )}
            {onOpenStudio ? (
              <button
                type="button"
                className={`app-header-menu-item ${currentPage === 'studio' ? 'active' : ''}`}
                onClick={onOpenStudio}
              >
                <Monitor size={15} />
                <span>Playbook Studio</span>
              </button>
            ) : (
              <Link className={`app-header-menu-item ${currentPage === 'studio' ? 'active' : ''}`} to={ROUTES.pbsStudio}>
                <Monitor size={15} />
                <span>Playbook Studio</span>
              </Link>
            )}
            {onOpenLibrary ? (
              <button
                type="button"
                className={`app-header-menu-item ${currentPage === 'library' ? 'active' : ''}`}
                onClick={onOpenLibrary}
              >
                <Library size={15} />
                <span>WIKI Library</span>
              </button>
            ) : (
              <Link className={`app-header-menu-item ${currentPage === 'library' ? 'active' : ''}`} to={ROUTES.pbsPlaybookLibrary}>
                <Library size={15} />
                <span>WIKI Library</span>
              </Link>
            )}
            <Link className="app-header-menu-item" to={ROUTES.pbsDetails}>
              <FileText size={15} />
              <span>Details</span>
            </Link>
            <div className="app-header-menu-divider" />
            <div className="app-header-menu-item app-header-menu-theme">
              <span>Theme</span>
              <ThemeToggleButton
                className="app-header-theme-btn"
                globalTheme={globalTheme}
                onToggleGlobalTheme={onToggleGlobalTheme}
              />
            </div>
          </div>
        </details>
      </div>
    </header>
  );
}
