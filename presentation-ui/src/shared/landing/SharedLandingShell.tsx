import { useSearchParams } from 'react-router-dom';
import LandingPage from '../../pages/LandingPage';
import { normalizeSharedLandingTab } from '../../app/routes';
import PartnerLanePanel from './PartnerLanePanel';
import './SharedLandingShell.css';

export default function SharedLandingShell() {
  const [searchParams] = useSearchParams();
  const activeTab = normalizeSharedLandingTab(searchParams.get('tab'));
  const isPartner = activeTab === 'partner';

  return (
    <div className={`shared-landing-shell ${isPartner ? 'partner-mode' : 'landing-mode'}`}>
      {isPartner ? (
        <div className="shared-shell-body">
          <PartnerLanePanel />
        </div>
      ) : (
        <LandingPage />
      )}
    </div>
  );
}
