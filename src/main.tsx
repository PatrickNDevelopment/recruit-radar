import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { SessionStore } from './data/session';
import { browserStorage } from './data/storage';
import { pageHostname } from './ui/environment';
import './styles.css';

const storage = browserStorage();
const store = new SessionStore({
  storage,
  pageHostname: pageHostname(),
  events: typeof window === 'undefined' ? null : window,
});

const container = document.getElementById('root');
if (container === null) throw new Error('The page has no #root element to render into.');

createRoot(container).render(
  <StrictMode>
    <App store={store} />
  </StrictMode>,
);
