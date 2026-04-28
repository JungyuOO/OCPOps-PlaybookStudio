import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import gsap from 'gsap';
import './MetricsFooter.css';
import { ROUTES } from '../app/routes';
import { loadDataControlRoom } from '../lib/runtimeApi';

export default function MetricsFooter() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [metrics, setMetrics] = useState({
    approvedRuntime: 0,
    customerUploadedPlaybooks: 0,
    pendingMaterials: 0,
  });

  useEffect(() => {
    let mounted = true;
    loadDataControlRoom()
      .then((payload) => {
        if (!mounted) {
          return;
        }
        setMetrics({
          approvedRuntime: Number(payload.summary.approved_runtime_count || 0),
          customerUploadedPlaybooks: Number(payload.summary.user_library_book_count || 0),
          pendingMaterials: Number(payload.summary.gold_candidate_book_count || 0),
        });
      })
      .catch(() => {
        if (!mounted) {
          return;
        }
        setMetrics({
          approvedRuntime: 0,
          customerUploadedPlaybooks: 0,
          pendingMaterials: 0,
        });
      });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    const ctx = gsap.context(() => {
      // Counter animation logic
      const counters = gsap.utils.toArray<HTMLElement>('.metric-number');

      counters.forEach((counter) => {
        const targetValue = Number.parseInt(counter.dataset.target || '0', 10);

        gsap.to(counter, {
          scrollTrigger: {
            trigger: containerRef.current,
            start: "top 80%",
            once: true
          },
          innerHTML: targetValue,
          duration: 2,
          ease: "power2.out",
          snap: { innerHTML: 1 },
          onUpdate: function () {
            const nextValue = Number.parseFloat(counter.innerHTML || '0');
            counter.innerHTML = String(Math.round(nextValue));
          }
        });
      });
    }, containerRef);
    return () => ctx.revert();
  }, [metrics]);

  return (
    <footer className="metrics-footer" ref={containerRef}>
      <div className="metrics-content">
        <h2>플랫폼 문서 현황</h2>
        <p className="metrics-intro">
          승인된 OCP 공식 매뉴얼, 고객 업로드 플레이북, 플레이북 반영 대기 자료를 기준으로 집계합니다.
        </p>

        <div className="metrics-grid">
          <div className="metric-item">
            <span className="metric-number gradient-text" data-target={metrics.approvedRuntime}>{metrics.approvedRuntime}</span>
            <span className="metric-label">OCP 공식 매뉴얼</span>
          </div>
          <div className="metric-item">
            <span className="metric-number gradient-text" data-target={metrics.customerUploadedPlaybooks}>{metrics.customerUploadedPlaybooks}</span>
            <span className="metric-label">고객 업로드 문서</span>
          </div>
          <div className="metric-item">
            <span className="metric-number gradient-text" data-target={metrics.pendingMaterials}>{metrics.pendingMaterials}</span>
            <span className="metric-label">반영 대기 자료</span>
          </div>
        </div>

        <div className="footer-cta">
          <Link to={ROUTES.pbsDetails} className="btn-primary">
            제품 소개
          </Link>
        </div>
      </div>

      <div className="footer-bottom">
        <p>Play Book Studio Enterprise — Red Hat OpenShift 4.20 / Designed by Cywell</p>
      </div>
    </footer>
  );
}
