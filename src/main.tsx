import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import { setFavicon } from './lib/icons';
import { App } from './App';

setFavicon();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
