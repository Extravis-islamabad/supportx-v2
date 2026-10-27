import { QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { RouterProvider } from 'react-router';

import { RealtimeProvider } from '@supportx/realtime';

import {
  AddressBranding,
  AppearanceProvider,
  createQueryClient,
  ErrorBoundary,
  ErrorReporterProvider,
  LicenceProvider,
  SessionGate,
  TenantBranding,
  type SessionGateProps,
} from '@supportx/ui';

import { createRouter } from './router';

export interface AppProps {
  /** For tests: replaces the browser navigation to the login page. */
  navigate?: SessionGateProps['navigate'];
}

export function App({ navigate }: AppProps) {
  // One cache and one router per mounted app (not module-level), so tests and HMR start clean.
  const [queryClient] = useState(createQueryClient);
  const [router] = useState(createRouter);
  return (
    <QueryClientProvider client={queryClient}>
      <AppearanceProvider>
        <AddressBranding />
        <ErrorBoundary>
          <ErrorReporterProvider>
            <SessionGate app="console" navigate={navigate}>
              {(session) => (
                // Keyed by tenant: a tenant switch remounts everything below with fresh state.
                <RealtimeProvider tenantId={session.tenant.id} userId={session.user.id}>
                  <TenantBranding />
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
