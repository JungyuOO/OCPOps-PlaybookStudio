import LandingPage from '../../pages/LandingPage';
import './SharedLandingShell.css';

export default function SharedLandingShell() {
  return (
    <div className="shared-landing-shell shared-landing-shell--pbs">
      <div className="shared-shell-body">
        <LandingPage />
      </div>
    </div>
  );
}
