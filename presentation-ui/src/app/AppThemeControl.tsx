import { useLocation } from 'react-router-dom';
import GlobalThemeToggle from '../components/GlobalThemeToggle';
import { useGlobalTheme } from '../lib/useGlobalTheme';
import { ROUTES } from './routes';

export default function AppThemeControl() {
  const location = useLocation();
  const [theme, toggleTheme] = useGlobalTheme();
  const path = location.pathname;
  const isWorkspace = path === ROUTES.pbsStudio || path === ROUTES.pbsWorkspaceAlias;
  const isLanding = path === ROUTES.sharedHome;

  if (isWorkspace) {
    return null;
  }

  return (
    <div className={`app-theme-control ${isLanding ? 'app-theme-control--landing' : 'app-theme-control--page'}`}>
      <GlobalThemeToggle theme={theme} onToggle={toggleTheme} />
    </div>
  );
}
