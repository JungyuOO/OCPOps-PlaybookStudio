import { ChevronDown, Languages, Sparkles, Moon, Sun } from 'lucide-react';
import { Link } from 'react-router-dom';
import { ROUTES, buildSharedLandingHref } from '../../app/routes';

type WorkspaceHeaderProps = {
  packDropdownOpen: boolean;
  packLabel: string;
  packOptions: readonly string[];
  sessionId: string;
  testMode: boolean;
  globalTheme: 'dark' | 'light';
  onOpenLibrary: () => void;
  onResetSession: () => void;
  onSelectPack: (label: string) => void;
  onTogglePackDropdown: () => void;
  onToggleTestMode: () => void;
  onToggleGlobalTheme: () => void;
};

export default function WorkspaceHeader({
  packDropdownOpen,
  packLabel,
  packOptions,
  sessionId,
  testMode,
  onOpenLibrary,
  onResetSession,
  onSelectPack,
  onTogglePackDropdown,
  onToggleTestMode,
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
        <span className="header-divider">|</span>
        <div className="pack-selector-wrapper">
          <button
            className="pack-selector-trigger"
            type="button"
            onClick={onTogglePackDropdown}
          >
            <span>{packLabel}</span>
            <ChevronDown size={14} className={`pack-chevron ${packDropdownOpen ? 'open' : ''}`} />
          </button>
          {packDropdownOpen && (
            <div className="pack-dropdown">
              {packOptions.map((label) => (
                <button
                  key={label}
                  type="button"
                  className={`pack-dropdown-item ${label === packLabel ? 'active' : ''}`}
                  onClick={() => {
                    onSelectPack(label);
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="nav-right">
        <div className="status-indicator" onClick={onResetSession} title="Click to start a new session">
          <div className="status-dot"></div>
          <span className="session-id-text">{sessionId}</span>
        </div>
        <div className="header-theme-controls">
          <button className="header-action-btn" onClick={onToggleGlobalTheme} title="Toggle Dark/Light Mode">
            {globalTheme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
          </button>
        </div>
        <button
          className={`nav-btn test-mode-btn ${testMode ? 'active' : ''}`}
          onClick={onToggleTestMode}
          type="button"
        >
          TEST
        </button>
        <Link to={ROUTES.opsOverview} className="nav-btn nav-link-btn">Ops Console</Link>
        <button className="nav-btn" onClick={onOpenLibrary} type="button">Playbook Library</button>
        <button className="nav-btn lang-btn" type="button">
          <Languages size={18} />
          <span>KOR</span>
        </button>
      </div>
    </header>
  );
}
