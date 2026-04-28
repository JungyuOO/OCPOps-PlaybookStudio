import { BrowserRouter as Router } from 'react-router-dom';
import { useEffect } from 'react';
import AppRoutes from './app/AppRoutes';
import AppThemeControl from './app/AppThemeControl';
import { applyGlobalTheme } from './lib/useGlobalTheme';
import './index.css';

function App() {
  useEffect(() => {
    applyGlobalTheme(window.localStorage.getItem('pbs.globalTheme') === 'light' ? 'light' : 'dark');
  }, []);

  return (
    <Router>
      <AppThemeControl />
      <AppRoutes />
    </Router>
  );
}

export default App;
