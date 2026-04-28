import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import './CoursePages.css';
import { ROUTES } from '../app/routes';
import { loadCourseManifest, type CourseManifest } from '../lib/courseApi';

const STAGE_SUMMARY: Record<string, string> = {
  architecture: '설계 산출물과 아키텍처 다이어그램을 운영 학습 순서로 따라갑니다.',
  unit_test: '단위 테스트 케이스를 검증 방법과 기대 상태 중심으로 학습합니다.',
  integration_test: 'CI/CD 통합 흐름을 파이프라인 실행부터 서비스 접근 확인까지 따라갑니다.',
  perf_test: '성능 목표, 결과, 병목, 개선 포인트를 순서대로 확인합니다.',
  completion: '완료보고서를 사업 범위, 구성 결과, 테스트 결과 순서로 정리합니다.',
};

export default function CourseTimelinePage() {
  const [manifest, setManifest] = useState<CourseManifest | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    void loadCourseManifest().then(setManifest).catch((caught) => {
      setError(caught instanceof Error ? caught.message : 'Failed to load course manifest');
    });
  }, []);

  const totalChunks = useMemo(
    () => (manifest?.stages ?? []).reduce((sum, stage) => sum + stage.chunk_refs.length, 0),
    [manifest],
  );

  return (
    <div className="course-page">
      <div className="course-shell">
        <header className="course-header">
          <h1>OCP Project Playbook Course</h1>
          <p>실제 사업 산출물을 운영 학습 순서로 따라가는 내부 교육 코스입니다.</p>
        </header>

        {error ? <div className="course-panel course-detail">{error}</div> : null}

        <section className="course-panel course-detail course-overview-card">
          <strong>{manifest?.title || 'Loading course timeline...'}</strong>
          <span className="course-muted">총 {(manifest?.stages ?? []).length} 단계 / {totalChunks} parent chunks</span>
          <p className="course-copy">
            각 단계는 PPT/PDF에서 추출한 Study-docs 근거를 기반으로 구성됩니다.
            사용자는 내부 문서 ID를 몰라도 추천 질문 카드를 따라가며 답변, 근거, 다음 절차를 이어서 확인할 수 있습니다.
          </p>
        </section>

        <section className="course-timeline">
          {(manifest?.stages ?? []).map((stage) => (
            <Link key={stage.stage_id} to={ROUTES.courseStage(stage.stage_id)} className="course-stage-link">
              <span className="course-step-index">Step {stage.order}</span>
              <strong>{stage.title}</strong>
              <span>{STAGE_SUMMARY[stage.stage_id] || '이 단계의 산출물과 공식문서를 함께 따라갑니다.'}</span>
              {stage.learning_route?.start_here?.length ? (
                <span className="course-route-teaser">
                  Start Here {stage.learning_route.start_here.length} / Then Open {stage.learning_route.then_open.length}
                </span>
              ) : null}
              <span className="course-stage-meta">{stage.chunk_refs.length} groups</span>
            </Link>
          ))}
        </section>

        <div className="course-inline-links">
          <Link to={ROUTES.pbsStudio}>Playbook Studio</Link>
          <Link to={ROUTES.pbsPlaybookLibrary}>Playbook Library</Link>
          <Link to={ROUTES.opsOverview}>Operations Console</Link>
        </div>
      </div>
    </div>
  );
}
