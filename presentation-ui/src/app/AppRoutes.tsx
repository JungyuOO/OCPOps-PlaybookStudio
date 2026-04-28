import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import WorkspacePage from '../pages/WorkspacePage';
import LlmWikiBookPage from '../pages/LlmWikiBookPage';
import PlaybookLibraryPage from '../pages/PlaybookLibraryPage';
import ProjectDetailsPage from '../pages/ProjectDetailsPage';
import OpsConsolePage from '../pages/OpsConsolePage';
import CourseTimelinePage from '../pages/CourseTimelinePage';
import CourseStagePage from '../pages/CourseStagePage';
import CourseChunkPage from '../pages/CourseChunkPage';
import CourseAtlasPage from '../pages/CourseAtlasPage';
import PartnerNamespacePage from '../partner/PartnerNamespacePage';
import { PARTNER_ROUTE_DEFINITIONS } from '../partner/partnerLaneConfig';
import SharedLandingShell from '../shared/landing/SharedLandingShell';
import { buildHandoffLocation } from './handoff';
import { ROUTES } from './routes';

function AliasRedirect({ to }: { to: string }) {
  const location = useLocation();

  return (
    <Navigate
      replace
      to={buildHandoffLocation(to, location)}
    />
  );
}

export default function AppRoutes() {
  return (
    <Routes>
      <Route path={ROUTES.sharedHome} element={<SharedLandingShell />} />
      <Route path={ROUTES.pbsDetails} element={<ProjectDetailsPage />} />
      <Route path={ROUTES.pbsStudio} element={<WorkspacePage />} />
      <Route path={ROUTES.pbsWikiBook} element={<LlmWikiBookPage />} />
      <Route path={ROUTES.pbsWikiBookAlias} element={<AliasRedirect to={ROUTES.pbsWikiBook} />} />
      <Route path={ROUTES.pbsWorkspaceAlias} element={<AliasRedirect to={ROUTES.pbsStudio} />} />
      <Route path={ROUTES.pbsPlaybookLibrary} element={<PlaybookLibraryPage />} />
      <Route path={ROUTES.pbsControlTower} element={<PlaybookLibraryPage />} />
      <Route path={ROUTES.pbsRepository} element={<PlaybookLibraryPage />} />
      <Route path={ROUTES.courseHome} element={<CourseTimelinePage />} />
      <Route path="/course/stages/:stageId" element={<CourseStagePage />} />
      <Route path="/course/chunks/:chunkId" element={<CourseChunkPage />} />
      <Route path="/course/atlas/:chunkId" element={<CourseAtlasPage />} />
      <Route path={ROUTES.opsWorkspaces} element={<OpsConsolePage />} />
      <Route path={ROUTES.opsConnections} element={<OpsConsolePage />} />
      <Route path={ROUTES.opsOverview} element={<OpsConsolePage />} />
      <Route path={ROUTES.opsResources} element={<OpsConsolePage />} />
      <Route path={ROUTES.opsLibrary} element={<OpsConsolePage />} />
      <Route path={ROUTES.opsChat} element={<OpsConsolePage />} />
      <Route path={ROUTES.opsActions} element={<OpsConsolePage />} />
      {PARTNER_ROUTE_DEFINITIONS.map(({ path, eyebrow, title, description }) => (
        <Route
          key={path}
          path={path}
          element={(
            <PartnerNamespacePage
              eyebrow={eyebrow}
              title={title}
              description={description}
            />
          )}
        />
      ))}
      <Route path="*" element={<Navigate replace to={ROUTES.sharedHome} />} />
    </Routes>
  );
}
