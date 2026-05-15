import { useEffect } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import Hero from '../components/Hero';
import PipelineScroller from '../components/PipelineScroller';
import ProductSurfaces from '../components/ProductSurfaces';
import MetricsFooter from '../components/MetricsFooter';
import ThemeToggleButton from '../components/ThemeToggleButton';
import { useGlobalTheme } from '../lib/globalTheme';
import './LandingPage.css';

gsap.registerPlugin(ScrollTrigger);

export default function LandingPage() {
  const { globalTheme, toggleGlobalTheme } = useGlobalTheme();

  useEffect(() => {
    // Standard ScrollTrigger update on scroll
    ScrollTrigger.refresh();
  }, []);

  return (
    <div className="app-container">
      <div className="landing-theme-controls">
        <ThemeToggleButton
          className="landing-theme-toggle-btn"
          globalTheme={globalTheme}
          onToggleGlobalTheme={toggleGlobalTheme}
        />
      </div>
      <Hero />
      <PipelineScroller />
      <ProductSurfaces />
      <MetricsFooter />
    </div>
  );
}
