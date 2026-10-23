import { QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { RouterProvider } from 'react-router';

import { RealtimeProvider } from '@supportx/realtime';

import {
  AppearanceProvider,
  createQueryClient,
  ErrorBoundary,
  ErrorReporterProvider,
  LicenceProvider,
  SessionGate,
  type SessionGateProps,
} from '@supportx/ui';

import { createRouter } from './router';

export interface AppProps {
  /** For tests: replaces the browser navigation to the login page. */
  navigate?: SessionGateProps['navigate'];
}

export function App({ navigate }: AppProps) {
  const [queryClient] = useState(createQueryClient);
  const [router] = useState(createRouter);
  return (
    <QueryClientProvider client={queryClient}>
      <AppearanceProvider>
        <ErrorBoundary>
          <ErrorReporterProvider>
            <SessionGate app="portal" navigate={navigate}>
              {(session) => (
                <RealtimeProvider tenantId={session.tenant.id} userId={session.user.id}>
                  <LicenceProvider key={session.tenant.id} session={session}>
                    <RouterProvider router={router} />
                  </LicenceProvider>
                </RealtimeProvider>
              )}
            </SessionGate>
          </ErrorReporterProvider>
        </ErrorBoundary>
      </AppearanceProvider>
    </QueryClientProvider>
  );
}
