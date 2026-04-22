import { Link, useSearchParams } from 'react-router-dom';
import LandingPage from '../../pages/LandingPage';
import { ROUTES, normalizeSharedLandingTab } from '../../app/routes';
import PartnerLanePanel from './PartnerLanePanel';
import SharedLandingSwitcher from './SharedLandingSwitcher';
import './SharedLandingShell.css';

export default function SharedLandingShell() {
  const [searchParams] = useSearchParams();
  const activeTab = normalizeSharedLandingTab(searchParams.get('tab'));

  return (
    <div className="shared-landing-shell">
      <SharedLandingSwitcher activeTab={activeTab} />
      <div className="shared-shell-utility-strip glass-panel">
        <div className="shared-shell-utility-copy">
          <strong>Current Spec Console</strong>
          <span>`/workspaces` ~ `/scm` 운영 콘솔을 기존 PBS 셸과 병행 노출합니다.</span>
        </div>
        <div className="shared-shell-utility-actions">
          <Link to={ROUTES.opsWorkspaces} className="shared-shell-utility-primary">Open Ops Console</Link>
          <Link to={ROUTES.pbsStudio} className="shared-shell-utility-secondary">Back to Studio</Link>
        </div>
      </div>

      <div className="shared-shell-body">
        {activeTab === 'partner' ? <PartnerLanePanel /> : <LandingPage />}
      </div>
    </div>
  );
}
