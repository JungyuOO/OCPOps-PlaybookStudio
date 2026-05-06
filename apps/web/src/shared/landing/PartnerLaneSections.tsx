import { ArrowRight, Waypoints } from 'lucide-react';
import { Link } from 'react-router-dom';
import { ROUTES } from '../../app/routes';
import { PARTNER_SURFACES } from '../../partner/partnerLaneConfig';

export function PartnerLaneHero() {
  return (
    <div className="partner-lane-hero glass-panel">
      <div className="partner-lane-copy">
        <span className="partner-lane-eyebrow">Partner Lane</span>
        <h2 className="partner-lane-title">Sibling namespace, not PBS takeover.</h2>
        <p className="partner-lane-description">
          상대 프로젝트는 shared landing에서 함께 소개되지만, 실제 기능 surface는
          <strong> `/partner/*` </strong>
          아래에서 분기됩니다. 이렇게 해야 PBS runtime truth와 route ownership이 깨지지 않습니다.
        </p>
      </div>
      <div className="partner-lane-actions">
        <Link to={ROUTES.partnerHome} className="partner-primary-link">
          <span>Open Partner Lane</span>
          <ArrowRight size={18} />
        </Link>
        <Link to={ROUTES.partnerDetails} className="partner-secondary-link">
          Integration Notes
        </Link>
      </div>
    </div>
  );
}

export function PartnerSurfaceGrid() {
  return (
    <div className="partner-surface-grid">
      {PARTNER_SURFACES.map(({ path, card }) => {
        const Icon = card.icon;
        return (
          <Link key={path} to={path} className="partner-surface-card glass-panel">
            <div className="partner-surface-icon">
              <Icon size={26} />
            </div>
            <h3>{card.title}</h3>
            <p>{card.description}</p>
          </Link>
        );
      })}
    </div>
  );
}

export function PartnerGuardRail() {
  return (
    <div className="partner-lane-guard glass-panel">
      <div className="partner-lane-guard-icon">
        <Waypoints size={22} />
      </div>
      <div>
        <h3>Merge-ready guardrail</h3>
        <p>
          PBS는 기존 경로
          <strong> `/studio`, `/llmwikibook`, `/playbook-library*` </strong>
          를 그대로 유지하고, partner 기능만 sibling subtree로 받아들입니다.
        </p>
      </div>
    </div>
  );
}
