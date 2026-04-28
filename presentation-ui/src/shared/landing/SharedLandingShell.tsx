import { useSearchParams } from 'react-router-dom';
import LandingPage from '../../pages/LandingPage';
import { normalizeSharedLandingTab } from '../../app/routes';
import PartnerLanePanel from './PartnerLanePanel';
import './SharedLandingShell.css';

export default function SharedLandingShell() {
  const [searchParams] = useSearchParams();
  const activeTab = normalizeSharedLandingTab(searchParams.get('tab'));

  return (
    <div className={`shared-landing-shell shared-landing-shell--${activeTab}`}>
      <div className="shared-shell-body">
        {activeTab === 'partner' ? <PartnerLanePanel /> : <LandingPage />}
      </div>
    </div>
  );
}
