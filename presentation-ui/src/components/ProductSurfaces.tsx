import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { Link } from 'react-router-dom';
import { MessageSquare, BookOpen, MonitorPlay, Cpu, Database } from 'lucide-react';
import { ROUTES } from '../app/routes';
import './ProductSurfaces.css';

export default function ProductSurfaces() {
  const containerRef = useRef<HTMLDivElement>(null);
  const cardsRef = useRef<(HTMLAnchorElement | null)[]>([]);

  useEffect(() => {
    const ctx = gsap.context(() => {
      // 3D Magnetic Mouse Tracking
      cardsRef.current.forEach(card => {
        if (!card) return;

        card.addEventListener("mousemove", (e) => {
          const rect = card.getBoundingClientRect();
          const x = e.clientX - rect.left; // x position within the element
          const y = e.clientY - rect.top; // y position within the element

          const centerX = rect.width / 2;
          const centerY = rect.height / 2;

          const rotateX = ((y - centerY) / centerY) * -10; // max 10 deg
          const rotateY = ((x - centerX) / centerX) * 10;

          gsap.to(card, {
            rotateX: rotateX,
            rotateY: rotateY,
            transformPerspective: 1000,
            ease: "power2.out",
            duration: 0.5
          });

          // Move the inner glow
          const glow = card.querySelector('.glow-orb') as HTMLElement;
          if (glow) {
            gsap.to(glow, {
              x: x - rect.width / 2,
              y: y - rect.height / 2,
              opacity: 1,
              ease: "power2.out",
              duration: 0.5
            });
          }
        });

        card.addEventListener("mouseleave", () => {
          gsap.to(card, {
            rotateX: 0,
            rotateY: 0,
            ease: "elastic.out(1, 0.3)",
            duration: 1.5
          });

          const glow = card.querySelector('.glow-orb') as HTMLElement;
          if (glow) {
            gsap.to(glow, { opacity: 0, duration: 0.5 });
          }
        });
      });

    }, containerRef);
    return () => ctx.revert();
  }, []);

  return (
    <section className="surfaces-container" ref={containerRef}>
      <div className="surfaces-header">
        <h2 className="text-hero">Product Surfaces</h2>
        <p className="text-subtitle">다섯가지의 연결된 인터페이스.</p>
      </div>

      <div className="surfaces-grid">

        <Link
          to={ROUTES.pbsStudio}
          className="surface-card glass-panel"
          ref={el => { cardsRef.current[0] = el; }}
        >
          <div className="glow-orb"></div>
          <div className="card-content">
            <div className="surface-icon">
              <MessageSquare size={48} color="var(--accent-cyan)" />
            </div>
            <h3>Studio</h3>
            <p>Playbot과 Playbook의 연계<br></br>운영과 학습을 위한 통합 스튜디오</p>
          </div>
        </Link>

        <Link
          to={ROUTES.opsWorkspaces}
          className="surface-card glass-panel"
          ref={el => { cardsRef.current[1] = el; }}
        >
          <div className="glow-orb"></div>
          <div className="card-content">
            <div className="surface-icon">
              <Cpu size={48} color="#e68a35" />
            </div>
            <h3>Ops Console</h3>
            <p>자동 복구 및 자동화, AI Ops</p>
          </div>
        </Link>

        <Link
          to={ROUTES.pbsPlaybookLibrary}
          className="surface-card glass-panel"
          ref={el => { cardsRef.current[2] = el; }}
        >
          <div className="glow-orb"></div>
          <div className="card-content">
            <div className="surface-icon">
              <BookOpen size={48} color="var(--text-main)" />
            </div>
            <h3>Playbook Library</h3>
            <p>모든 Playbook을 모아놓은 <br></br>중앙 도서관</p>
          </div>
        </Link>

        <Link
          to={ROUTES.pbsRepository}
          className="surface-card glass-panel"
          ref={el => { cardsRef.current[3] = el; }}
        >
          <div className="glow-orb"></div>
          <div className="card-content">
            <div className="surface-icon">
              <Database size={48} color="#10b981" />
            </div>
            <h3>Book Factory</h3>
            <p>공식 문서와 유저 문서를<br></br>위키형 책과 챗봇 코퍼스로 자동 변환</p>
          </div>
        </Link>

        <Link
          to={ROUTES.pbsControlTower}
          className="surface-card glass-panel"
          ref={el => { cardsRef.current[4] = el; }}
        >
          <div className="glow-orb"></div>
          <div className="card-content">
            <div className="surface-icon">
              <MonitorPlay size={48} color="var(--accent-purple)" />
            </div>
            <h3>Control Tower</h3>
            <p>현황과 품질, 평가 리포트를<br></br>한 눈에 점검하는 상황실</p>
          </div>
        </Link>

      </div>
    </section>
  );
}
