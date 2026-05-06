import { Layers3, Sparkles } from 'lucide-react';
import { Link } from 'react-router-dom';
import { buildSharedLandingHref, type SharedLandingTab } from '../../app/routes';

export default function SharedLandingSwitcher({ activeTab }: { activeTab: SharedLandingTab }) {
  return (
    <div className="shared-shell-switcher glass-panel">
      <div>
        <div className="shared-shell-label">
          <Layers3 size={16} />
          <span>Shared Entry Shell</span>
        </div>
        <h1 className="shared-shell-title">
          One landing, two product lanes.
        </h1>
        <p className="shared-shell-description">
          루트 랜딩은 공유하지만 PBS의 runtime truth와 route ownership은 그대로 유지합니다.
          partner 기능은 sibling namespace로 유입되고, PBS core surface는 기존 경로를 계속 사용합니다.
        </p>
      </div>
      <div className="shared-shell-tabs" aria-label="Product lane selector">
        <Link
          to={buildSharedLandingHref('pbs')}
          className={`shared-shell-tab ${activeTab === 'pbs' ? 'is-active' : ''}`}
        >
          <Sparkles size={16} />
          <span>PBS Lane</span>
        </Link>
        <Link
          to={buildSharedLandingHref('partner')}
          className={`shared-shell-tab ${activeTab === 'partner' ? 'is-active' : ''}`}
        >
          <Layers3 size={16} />
          <span>Partner Lane</span>
        </Link>
      </div>
    </div>
  );
}
