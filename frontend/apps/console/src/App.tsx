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
  PASSWORD_RESET_PATH,
  PasswordResetPage,
  SessionGate,
  TenantBranding,
  type SessionGateProps,
} from '@supportx/ui';

import { createRouter } from './router';
import { SSO_TEST_DONE_PATH, SsoTestDonePage } from './pages/admin/security/SsoTestDonePage';

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
            {window.location.pathname === SSO_TEST_DONE_PATH ? (
              // The SSO test's landing page needs no session: the test may run in a private
              // window, signed in as nobody (WP-039).
              <SsoTestDonePage />
            ) : window.location.pathname === PASSWORD_RESET_PATH ? (
              // "Forgot password?" is for people who cannot sign in (WP-039 session 2).
              <PasswordResetPage app="console" />
            ) : (
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
            )}
          </ErrorReporterProvider>
        </ErrorBoundary>
      </AppearanceProvider>
    </QueryClientProvider>
  );
}
