import { BrowserRouter as Router } from 'react-router-dom';
import AppRoutes from './app/AppRoutes';
import './index.css';

function App() {
  return (
    <Router>
      <AppRoutes />
    </Router>
  );
}

export default App;
