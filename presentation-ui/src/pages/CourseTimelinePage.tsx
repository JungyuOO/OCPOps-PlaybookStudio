import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import './CoursePages.css';
import { ROUTES } from '../app/routes';
import { loadCourseManifest, loadLearningPaths, type CourseManifest, type LearningPathCatalog, type LearningStep } from '../lib/courseApi';

const STAGE_SUMMARY: Record<string, string> = {
  architecture: '설계 산출물과 아키텍처 다이어그램을 운영 학습 순서로 따라갑니다.',
  unit_test: '단위 테스트 케이스를 검증 방법과 기대 상태 중심으로 학습합니다.',
  integration_test: 'CI/CD 통합 흐름을 파이프라인 실행부터 서비스 접근 확인까지 따라갑니다.',
  perf_test: '성능 목표, 결과, 병목, 개선 포인트를 순서대로 확인합니다.',
  completion: '완료보고서를 사업 범위, 구성 결과, 테스트 결과 순서로 정리합니다.',
};

export default function CourseTimelinePage() {
  const [manifest, setManifest] = useState<CourseManifest | null>(null);
  const [learningCatalog, setLearningCatalog] = useState<LearningPathCatalog | null>(null);
  const [error, setError] = useState('');
  const [learningError, setLearningError] = useState('');
  const [selectedStepKey, setSelectedStepKey] = useState('');

  useEffect(() => {
    void loadCourseManifest().then(setManifest).catch((caught) => {
      setError(caught instanceof Error ? caught.message : 'Failed to load course manifest');
    });
    void loadLearningPaths(5).then(setLearningCatalog).catch((caught) => {
      setLearningError(caught instanceof Error ? caught.message : 'Failed to load learning paths');
    });
  }, []);

  const totalChunks = useMemo(
    () => (manifest?.stages ?? []).reduce((sum, stage) => sum + stage.chunk_refs.length, 0),
    [manifest],
  );
  const primaryLearningPath = learningCatalog?.paths?.[0] ?? null;
  const primarySteps = primaryLearningPath?.steps ?? [];
  const selectedStep: LearningStep | null = primarySteps.find((step) => step.step_key === selectedStepKey)
    ?? primarySteps[0]
    ?? null;
  const totalLabs = primarySteps.reduce((sum, step) => sum + step.lab_tasks.length, 0);
  const totalChecks = primarySteps.reduce(
    (sum, step) => sum + step.lab_tasks.reduce((taskSum, task) => taskSum + task.command_checks.length, 0),
    0,
  );

  return (
    <div className="course-page">
      <div className="course-shell">
        <header className="course-header">
          <h1>OCP Project Playbook Course</h1>
          <p>실제 사업 산출물을 운영 학습 순서로 따라가는 내부 교육 코스입니다.</p>
        </header>

        {error ? <div className="course-panel course-detail">{error}</div> : null}
        {learningError ? <div className="course-panel course-detail">{learningError}</div> : null}

        <section className="course-panel course-detail course-overview-card">
          <strong>{manifest?.title || 'Loading course timeline...'}</strong>
          <span className="course-muted">총 {(manifest?.stages ?? []).length} 단계 / {totalChunks} parent chunks</span>
          <p className="course-copy">
            각 단계는 PPT/PDF에서 추출한 실운영 근거를 기반으로 구성됩니다.
            사용자는 내부 문서 ID를 몰라도 추천 질문 카드를 따라가며 답변, 근거, 다음 절차를 이어서 확인할 수 있습니다.
          </p>
        </section>

        <section className="course-panel course-detail course-learning-path-panel">
          <div className="course-learning-path-head">
            <div>
              <span className="course-route-kicker">PostgreSQL Curriculum</span>
              <strong>{primaryLearningPath?.title || 'Learning path is waiting for seed import'}</strong>
              <p className="course-copy">
                {primaryLearningPath
                  ? primaryLearningPath.description || 'DB에 저장된 단계별 학습 경로를 기준으로 수업, 실습, 명령어 검증을 구성합니다.'
                  : learningCatalog?.unavailable_reason || 'learning-seed-import 실행 후 DB 기반 학습 경로가 여기에 표시됩니다.'}
              </p>
            </div>
            <div className="course-learning-path-metrics">
              <span><strong>{primarySteps.length}</strong> Steps</span>
              <span><strong>{totalLabs}</strong> Labs</span>
              <span><strong>{totalChecks}</strong> Checks</span>
            </div>
          </div>
          {primarySteps.length > 0 ? (
            <div className="course-learning-step-strip">
              {primarySteps.slice(0, 6).map((step) => (
                <button
                  key={step.id}
                  className={`course-learning-step-card ${selectedStep?.step_key === step.step_key ? 'active' : ''}`}
                  type="button"
                  onClick={() => setSelectedStepKey(step.step_key)}
                >
                  <span>Step {step.ordinal}</span>
                  <strong>{step.title}</strong>
                  <p>{step.objective || '이 단계의 목표는 DB curriculum seed에서 관리됩니다.'}</p>
                  <div className="course-learning-step-meta">
                    <span>{step.estimated_minutes || 0} min</span>
                    <span>{step.lab_tasks.length} labs</span>
                    <span>{step.difficulty || 'beginner'}</span>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="course-learning-empty">
              <span>DB 기반 학습 경로가 준비되면 단계별 수업과 실습 검증이 표시됩니다.</span>
            </div>
          )}
          {selectedStep ? (
            <div className="course-learning-step-detail">
              <div className="course-learning-lesson">
                <span className="course-route-kicker">Selected Step</span>
                <strong>{selectedStep.title}</strong>
                <p>{selectedStep.objective || 'No objective provided yet.'}</p>
                {selectedStep.lesson_markdown ? <pre>{selectedStep.lesson_markdown}</pre> : null}
              </div>
              <div className="course-learning-lab-list">
                {selectedStep.lab_tasks.length > 0 ? selectedStep.lab_tasks.map((task) => (
                  <article key={task.id} className="course-learning-lab-card">
                    <span>Lab {task.ordinal}</span>
                    <strong>{task.title}</strong>
                    <p>{task.goal_markdown || 'No lab goal provided yet.'}</p>
                    {task.command_checks.length > 0 ? (
                      <div className="course-learning-command-list">
                        {task.command_checks.map((check) => (
                          <div key={check.id} className="course-learning-command-row">
                            <code>{check.expected_command || check.command_pattern || check.check_key}</code>
                            <span>{check.validation_kind}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <span className="course-muted">No command checks yet</span>
                    )}
                  </article>
                )) : (
                  <div className="course-learning-empty">
                    <span>No labs are attached to this step yet.</span>
                  </div>
                )}
              </div>
            </div>
          ) : null}
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
