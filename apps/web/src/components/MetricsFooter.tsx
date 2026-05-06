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
    topicPlaybooks: 0,
    playableAssets: 0,
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
          topicPlaybooks: Number(payload.summary.topic_playbook_count || 0),
          playableAssets: Number(payload.summary.playable_asset_count || 0),
        });
      })
      .catch(() => {
        if (!mounted) {
          return;
        }
        setMetrics({
          approvedRuntime: 0,
          topicPlaybooks: 0,
          playableAssets: 0,
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
        <h2>지금 바로 플랫폼에 검증된 지식</h2>

        <div className="metrics-grid">
          <div className="metric-item">
            <span className="metric-number gradient-text" data-target={metrics.approvedRuntime}>{metrics.approvedRuntime}</span>
            <span className="metric-label">Approved Runtime Books</span>
          </div>
          <div className="metric-item">
            <span className="metric-number gradient-text" data-target={metrics.topicPlaybooks}>{metrics.topicPlaybooks}</span>
            <span className="metric-label">Topic Playbooks</span>
          </div>
          <div className="metric-item">
            <span className="metric-number gradient-text" data-target={metrics.playableAssets}>{metrics.playableAssets}</span>
            <span className="metric-label">Playable Assets</span>
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
