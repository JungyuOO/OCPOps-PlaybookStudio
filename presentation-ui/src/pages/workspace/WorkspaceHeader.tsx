import { Sparkles, Moon, Sun } from 'lucide-react';
import { Link } from 'react-router-dom';
import { ROUTES, buildSharedLandingHref } from '../../app/routes';

type WorkspaceHeaderProps = {
  globalTheme: 'dark' | 'light';
  onOpenLibrary: () => void;
  onToggleGlobalTheme: () => void;
};

export default function WorkspaceHeader({
  onOpenLibrary,
  onToggleGlobalTheme,
  globalTheme,
}: WorkspaceHeaderProps) {
  return (
    <header className="workspace-nav">
      <div className="nav-left">
        <Link to={buildSharedLandingHref('pbs')} className="nav-logo-link">
          <div className="logo-icon">
            <Sparkles size={20} />
          </div>
        </Link>
        <span className="logo-text">Playbook Studio</span>
      </div>
      <div className="nav-right">
        <div className="header-theme-controls">
          <button className="header-action-btn" onClick={onToggleGlobalTheme} title="Toggle Dark/Light Mode">
            {globalTheme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
          </button>
        </div>
        <Link to={ROUTES.opsOverview} className="nav-btn nav-link-btn">Ops Console</Link>
        <button className="nav-btn" onClick={onOpenLibrary} type="button">Playbook Library</button>
      </div>
    </header>
  );
}
