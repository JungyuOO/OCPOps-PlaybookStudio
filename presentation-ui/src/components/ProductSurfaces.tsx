import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { Link } from 'react-router-dom';
import { MessageSquare, BookOpen, MonitorPlay } from 'lucide-react';
import { ROUTES } from '../app/routes';
import './ProductSurfaces.css';

export default function ProductSurfaces() {
  const containerRef = useRef<HTMLDivElement>(null);
  const cardsRef = useRef<(HTMLAnchorElement | null)[]>([]);

  useEffect(() => {
    const ctx = gsap.context(() => {
      // Entrance Animation
      gsap.from(cardsRef.current, {
        scrollTrigger: {
          trigger: containerRef.current,
          start: "top 70%",
        },
        y: 100,
        scale: 0.9,
        opacity: 0,
        stagger: 0.15,
        duration: 1.2,
        ease: "power3.out"
      });

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
        <p className="text-subtitle">어떻게 보여줄 것인가. 세 가지의 연결된 인터페이스.</p>
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
            <p>Playbot과 근거 문서를 함께 여는 운영 스튜디오</p>
          </div>
        </Link>

        <Link
          to={ROUTES.pbsPlaybookLibrary}
          className="surface-card glass-panel"
          ref={el => { cardsRef.current[1] = el; }}
        >
          <div className="glow-orb"></div>
          <div className="card-content">
            <div className="surface-icon">
              <BookOpen size={48} color="var(--text-main)" />
            </div>
            <h3>Playbook Library</h3>
            <p>Citation을 클릭하면 펼쳐지는 정확한 섹션 이동</p>
          </div>
        </Link>

        <Link
          to={ROUTES.pbsControlTower}
          className="surface-card glass-panel"
          ref={el => { cardsRef.current[2] = el; }}
        >
          <div className="glow-orb"></div>
          <div className="card-content">
            <div className="surface-icon">
              <MonitorPlay size={48} color="var(--accent-purple)" />
            </div>
            <h3>Control Tower</h3>
            <p>현황과 품질, 평가 리포트를 한 눈에 점검하는 상황실</p>
          </div>
        </Link>

      </div>
    </section>
  );
}
