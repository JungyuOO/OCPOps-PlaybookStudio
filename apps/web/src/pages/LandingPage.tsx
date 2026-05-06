import { useEffect } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import Hero from '../components/Hero';
import PipelineScroller from '../components/PipelineScroller';
import ProductSurfaces from '../components/ProductSurfaces';
import MetricsFooter from '../components/MetricsFooter';

gsap.registerPlugin(ScrollTrigger);

export default function LandingPage() {
  useEffect(() => {
    // Standard ScrollTrigger update on scroll
    ScrollTrigger.refresh();
  }, []);

  return (
    <div className="app-container">
      <Hero />
      <PipelineScroller />
      <ProductSurfaces />
      <MetricsFooter />
    </div>
  );
}
