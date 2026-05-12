import { Sparkles } from 'lucide-react';
import { Link } from 'react-router-dom';
import ThemeToggleButton from '../../components/ThemeToggleButton';
import { buildSharedLandingHref } from '../../routing/routes';

type WorkspaceHeaderProps = {
  globalTheme: 'dark' | 'light';
  onOpenDashboard: () => void;
  onOpenLibrary: () => void;
  onToggleGlobalTheme: () => void;
};

export default function WorkspaceHeader({
  onOpenDashboard,
  onOpenLibrary,
  onToggleGlobalTheme,
  globalTheme,
}: WorkspaceHeaderProps) {
  return (
    <header className="workspace-nav">
      <div className="nav-left">
        <Link to={buildSharedLandingHref()} className="nav-logo-link">
          <div className="logo-icon">
            <Sparkles size={20} />
          </div>
        </Link>
        <span className="logo-text">Playbook Studio</span>
      </div>
      <div className="nav-right">
        <button className="nav-btn" onClick={onOpenDashboard} type="button">Dashboard</button>
        <button className="nav-btn" onClick={onOpenLibrary} type="button">Playbook Library</button>
        <div className="header-theme-controls">
          <ThemeToggleButton
            className="header-action-btn"
            globalTheme={globalTheme}
            onToggleGlobalTheme={onToggleGlobalTheme}
          />
        </div>
      </div>
    </header>
  );
}
