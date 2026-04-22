import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Book, ShieldCheck, Layers, MessageSquare, PlaySquare } from 'lucide-react';
import gsap from 'gsap';
import { ROUTES, buildSharedLandingHref } from '../app/routes';
import './ProjectDetailsPage.css';

export default function ProjectDetailsPage() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Basic entrance animation for the page
    gsap.fromTo(containerRef.current,
      { opacity: 0, y: 50 },
      { opacity: 1, y: 0, duration: 1, ease: 'power3.out' }
    );
  }, []);

  return (
    <div className="details-page-wrapper" ref={containerRef}>

      {/* Sidebar Navigation */}
      <nav className="details-sidebar glass-panel">
        <div className="sidebar-header">
          <Link to={buildSharedLandingHref('pbs')} className="back-link">
            <ArrowLeft size={20} />
            <span>Back to Home</span>
          </Link>
          <h2 className="sidebar-title gradient-text">Project Contracts</h2>
          <Link to={ROUTES.opsWorkspaces} className="details-ops-link">
            <span>Open Ops Console</span>
          </Link>
        </div>

        <ul className="sidebar-menu">
          <li><a href="#core-charter"><Book size={16} /> 제품 헌장</a></li>
          <li><a href="#foundry-pipeline"><Layers size={16} /> 지식 제련 파이프라인</a></li>
          <li><a href="#chatbot-spine"><MessageSquare size={16} /> 챗봇 작동 시퀀스</a></li>
          <li><a href="#air-gapped"><ShieldCheck size={16} /> 폐쇄망 운영 전략</a></li>
          <li><a href="#roadmap"><PlaySquare size={16} /> 2026 로드맵</a></li>
        </ul>
      </nav>

      {/* Main Content Area */}
      <main className="details-content">

        <section id="core-charter" className="detail-section">
          <h1>Product Core Charter</h1>
          <p className="lead-text">
            PlayBookStudio는 흔한 요약형 챗봇이 아닙니다. 이 플랫폼의 본질은 방대한 공식 문서와 기업의 암묵지를 <strong>'실행 가능한 플레이북(Playbook)'</strong>으로 변환하는 데이터 제련소(Data Foundry)입니다.
          </p>
          <div className="status-banner">
            <span className="status-label">Product Status:</span>
            <span className="status-value gradient-text">2026 Best Product 선정 / Enterprise Grade</span>
            <span className="status-label ms-auto">Active Target:</span>
            <span className="status-value text-white">OpenShift 4.20 + Private Hybrid</span>
          </div>
        </section>

        <section id="foundry-pipeline" className="detail-section animate-in">
          <h2>1. 지식 제련 파이프라인 (Data Foundry)</h2>
          <p>로우 데이터가 어떻게 승인된 지식 자산으로 승격되는지를 정의하는 3단계 메달리온 아키텍처와 품질 게이트입니다.</p>
          <div className="pipeline-steps-grid">
            <div className="pipeline-card glass-panel">
              <div className="step-tag bronze">BRONZE</div>
              <h3>Harvest & Discovery</h3>
              <p>공식 Repo(AsciiDoc)와 비정형 소스를 추수하고, 소스 계보(Lineage)를 영구 기록하는 단계.</p>
            </div>
            <div className="pipeline-card glass-panel">
              <div className="step-tag silver">SILVER</div>
              <h3>Canonical Structure</h3>
              <p>원문의 구조를 완벽히 복원한 'Structured Book'을 생성하고 고정밀 한국어 번안을 수행하는 단계.</p>
            </div>
            <div className="pipeline-card glass-panel">
              <div className="step-tag gold">GOLD</div>
              <h3>Synthesis & Asset</h3>
              <p>트러블슈팅, 운영 가이드 등 목적별 플레이북으로 지식을 합성하고 챗봇용 코퍼스로 투영하는 단계.</p>
            </div>
          </div>
          <div className="status-banner gate-banner">
            <span className="status-label">Validation Gate:</span>
            <span className="status-value">14종 이상의 엄격한 품질 규칙을 통과해야 배포 대상(Active)이 됩니다.</span>
          </div>
        </section>



        <section id="chatbot-spine" className="detail-section animate-in">
          <h2>2. 챗봇 작동 시퀀스 (Chatbot Spine)</h2>
          <p>PBS의 챗봇은 환각(Hallucination) 없이 가장 권위 있는 소스만을 참조하여 답변을 생성합니다.</p>
          <div className="algo-flow-container">
            <div className="algo-card glass-panel">
              <div className="algo-icon"><Layers size={20} /></div>
              <h4>Hybrid Retrieval</h4>
              <p>키워드 기반(BM25)과 의미 기반(Vector) 검색을 결합하여 질문의 의도를 99% 포착합니다.</p>
            </div>
            <div className="algo-card glass-panel">
              <div className="algo-icon"><ShieldCheck size={20} /></div>
              <h4>Shared Truth Discipline</h4>
              <p>답변의 본문과 위키 뷰어의 원문이 정확히 일치하여, 인용구 클릭 시 해당 섹션으로 즉시 랜딩됩니다.</p>
            </div>
            <div className="algo-card glass-panel">
              <div className="algo-icon"><PlaySquare size={20} /></div>
              <h4>Cross-Encoder Reranking</h4>
              <p>추출된 근거들을 다시 한번 정밀 채점하여 가장 품질이 높은 단락만을 답변 생성에 사용합니다.</p>
            </div>
          </div>
        </section>

        <section id="air-gapped" className="detail-section animate-in">
          <h2>3. 폐쇄망 운영 및 학습 전략</h2>
          <p>보안이 극도로 강화된 폐쇄망(Air-gapped) 환경에서의 신속한 기술 습득과 도구 운영을 지원합니다.</p>
          <div className="strategy-grid">
            <div className="strategy-card">
              <h3>Professional Tool Learning</h3>
              <p>`oc cli`, `kubectl` 등 전문적인 운영 도구의 복잡한 절차를 인터넷 없이도 로컬 런타임 위키와 챗봇으로 실시간 학습할 수 있습니다.</p>
            </div>
            <div className="strategy-card">
              <h3>Knowledge Sovereignty</h3>
              <p>기업 내부의 민감한 지식이 외부로 유출되지 않으면서도, 최신 벤더 문서의 권위를 그대로 유지하며 사내 정책을 오버레이합니다.</p>
            </div>
          </div>
        </section>

        <section id="roadmap" className="detail-section animate-in">
          <h2>4. 시연 가능 품목 vs 2026 로드맵</h2>
          <div className="roadmap-container glass-panel">
            <div className="roadmap-column">
              <h3 className="text-white">Now (Demonstrable)</h3>
              <ul className="roadmap-list done">
                <li>공식 소스 기반 고정 파이프라인 (Validated Ingestion)</li>
                <li>Grounded Chat & Precise Citation Landing</li>
                <li>High-fidelity Play View (원문 구조 복원)</li>
                <li>Interactive Workspace Overlay (메모/체크리스트)</li>
              </ul>
            </div>
            <div className="roadmap-column">
              <h3 className="gradient-text">2026 Roadmap</h3>
              <ul className="roadmap-list pending">
                <li>Multi-Agent Autonomous Synthesis (완전 자동 지식 합성)</li>
                <li>Predictive Error Prevention (장애 사전 방어체계)</li>
                <li>Predictive Operation Guide (Next Play 2.0 시각화)</li>
                <li>Unified Control Tower (품질 및 가용성 실시간 대시보드)</li>
              </ul>
            </div>
          </div>
        </section>

      </main>

    </div>
  );
}
