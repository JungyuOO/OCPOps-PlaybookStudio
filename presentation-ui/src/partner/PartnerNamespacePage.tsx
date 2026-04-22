import { ArrowLeftRight, ShieldCheck, SplitSquareVertical } from 'lucide-react';
import { Link } from 'react-router-dom';
import { buildSharedLandingHref } from '../app/routes';
import './PartnerNamespacePage.css';

type PartnerNamespacePageProps = {
  eyebrow: string;
  title: string;
  description: string;
};

export default function PartnerNamespacePage({
  eyebrow,
  title,
  description,
}: PartnerNamespacePageProps) {
  return (
    <div className="partner-namespace-page">
      <div className="partner-namespace-shell">
        <Link to={buildSharedLandingHref('partner')} className="partner-namespace-back">
          <ArrowLeftRight size={18} />
          <span>Back to Shared Landing</span>
        </Link>

        <section className="partner-namespace-card glass-panel">
          <span className="partner-namespace-eyebrow">{eyebrow}</span>
          <h1 className="partner-namespace-title">{title}</h1>
          <p className="partner-namespace-description">{description}</p>
        </section>

        <div className="partner-namespace-grid">
          <section className="glass-panel">
            <SplitSquareVertical size={22} />
            <h3>Namespace isolation</h3>
            <p>
              이 lane은 partner 기능을 위한 sibling subtree이며, PBS core route family와
              citation deep link를 덮어쓰지 않습니다.
            </p>
          </section>
          <section className="glass-panel">
            <ShieldCheck size={22} />
            <h3>Truth isolation</h3>
            <p>
              shared landing은 entry shell만 공유합니다. runtime truth, corpus, citation map ownership은 PBS에 남습니다.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
