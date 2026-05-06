import { PartnerGuardRail, PartnerLaneHero, PartnerSurfaceGrid } from './PartnerLaneSections';

export default function PartnerLanePanel() {
  return (
    <section className="partner-lane-panel">
      <PartnerLaneHero />
      <PartnerSurfaceGrid />
      <PartnerGuardRail />
    </section>
  );
}
