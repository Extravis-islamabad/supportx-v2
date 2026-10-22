import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Layout } from 'antd';
import { useState } from 'react';

import { useLogout } from '@supportx/api-client';
import { AppearanceProvider, AppHeader, SessionGate, type SessionGateProps } from '@supportx/ui';

import { HomePage } from './HomePage';

export interface AppProps {
  /** For tests: replaces the browser navigation to the login page. */
  navigate?: SessionGateProps['navigate'];
}

function Shell({ navigate }: AppProps) {
  const logout = useLogout();
  return (
    <SessionGate app="portal" navigate={navigate}>
      {(session) => (
        <Layout style={{ minHeight: '100vh' }}>
          <AppHeader
            appName="app.portal.name"
            session={session}
            onLogout={() => {
              void logout();
            }}
          />
          <HomePage />
        </Layout>
      )}
    </SessionGate>
  );
}

export function App({ navigate }: AppProps) {
  // One cache per mounted app (not module-level), so tests and HMR start clean.
  const [queryClient] = useState(() => new QueryClient());
  return (
    <QueryClientProvider client={queryClient}>
      <AppearanceProvider>
        <Shell navigate={navigate} />
      </AppearanceProvider>
    </QueryClientProvider>
  );
}
