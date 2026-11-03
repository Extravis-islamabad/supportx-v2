import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { setClientApp } from '@supportx/api-client';

import { App } from './App';

// Every call says which app made it from the very first one (/auth/me included): the server
// refuses the console to requester-only people even on a shared host (D-129).
setClientApp('console');

const container = document.getElementById('root');
if (container === null) {
  throw new Error('Root element #root not found');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
