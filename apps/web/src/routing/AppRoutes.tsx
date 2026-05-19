import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import WorkspacePage from '../pages/WorkspacePage';
import LlmWikiBookPage from '../pages/LlmWikiBookPage';
import PlaybookLibraryPage from '../pages/PlaybookLibraryPage';
import CourseTimelinePage from '../pages/CourseTimelinePage';
import CourseStagePage from '../pages/CourseStagePage';
import CourseChunkPage from '../pages/CourseChunkPage';
import CourseAtlasPage from '../pages/CourseAtlasPage';
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
      <Route path={ROUTES.sharedHome} element={<WorkspacePage />} />
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
      <Route path={ROUTES.opsWorkspaces} element={<AliasRedirect to={ROUTES.pbsStudio} />} />
      <Route path={ROUTES.opsConnections} element={<AliasRedirect to={ROUTES.pbsStudio} />} />
      <Route path={ROUTES.opsOverview} element={<AliasRedirect to={ROUTES.pbsStudio} />} />
      <Route path={ROUTES.opsResources} element={<AliasRedirect to={ROUTES.pbsStudio} />} />
      <Route path={ROUTES.opsLibrary} element={<AliasRedirect to={ROUTES.pbsPlaybookLibrary} />} />
      <Route path={ROUTES.opsChat} element={<AliasRedirect to={ROUTES.pbsStudio} />} />
      <Route path={ROUTES.opsActions} element={<AliasRedirect to={ROUTES.pbsStudio} />} />
      <Route path="*" element={<Navigate replace to={ROUTES.pbsStudio} />} />
    </Routes>
  );
}
