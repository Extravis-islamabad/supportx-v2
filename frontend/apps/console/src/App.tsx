import { QueryClientProvider } from '@tanstack/react-query';
import { Spin } from 'antd';
import { useEffect, useState } from 'react';
import { RouterProvider } from 'react-router';

import { loginUrl } from '@supportx/api-client';
import { RealtimeProvider } from '@supportx/realtime';

import {
  AddressBranding,
  AppearanceProvider,
  ConfirmedPage,
  storedLocale,
  CrumbProvider,
  createQueryClient,
  DevSignInPage,
  ErrorBoundary,
  ErrorReporterProvider,
  isConfirmedPage,
  isDevSignIn,
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

/** D-129: holding no role but `requester` (or none) means the portal, never the console. */
function requesterOnly(roles: string[]): boolean {
  return roles.every((role) => role === 'requester');
}

/**
 * Requester-only people never work in the console (D-129, WP-028): the BFF sends them to the
 * portal at sign-in and ends a console session at /me; this is the screen's backstop. The
 * portal's sign-in completes silently on Keycloak's own session.
 */
function ToPortal({
  navigate = (url: string) => {
    window.location.assign(url);
  },
}: AppProps) {
  useEffect(() => {
    navigate(loginUrl('portal', '/'));
  }, [navigate]);
  return <Spin fullscreen />;
}

export function App({ navigate }: AppProps) {
  // One cache and one router per mounted app (not module-level), so tests and HMR start clean.
  const [queryClient] = useState(createQueryClient);
  const [router] = useState(createRouter);
  return (
    <QueryClientProvider client={queryClient}>
      <AppearanceProvider density="compact" initialLocale={storedLocale() ?? undefined}>
        <AddressBranding />
        <ErrorBoundary>
          <ErrorReporterProvider>
            {isConfirmedPage(window.location.pathname) ? (
              // A confirmation's landing (REQ-SEC-027): it tells the opener and closes. Outside
              // the session gate, so it never starts a sign-in of its own.
              <ConfirmedPage />
            ) : window.location.pathname === SSO_TEST_DONE_PATH ? (
              // The SSO test's landing page needs no session: the test may run in a private
              // window, signed in as nobody (WP-039).
              <SsoTestDonePage />
            ) : window.location.pathname === PASSWORD_RESET_PATH ? (
              // "Forgot password?" is for people who cannot sign in (WP-039 session 2).
              <PasswordResetPage app="console" />
            ) : isDevSignIn(window.location.pathname) ? (
              // Dev-only quick sign-in (D-151): the API answers 404 anywhere but the local stack.
              <DevSignInPage />
            ) : (
              <SessionGate app="console" navigate={navigate}>
                {(session) =>
                  requesterOnly(session.user.roles) ? (
                    <ToPortal navigate={navigate} />
                  ) : (
                    // Keyed by tenant: a tenant switch remounts everything below with fresh state.
                    <RealtimeProvider tenantId={session.tenant.id} userId={session.user.id}>
                      <TenantBranding />
                      <LicenceProvider key={session.tenant.id} session={session}>
                        <CrumbProvider>
                          <RouterProvider router={router} />
                        </CrumbProvider>
                      </LicenceProvider>
                    </RealtimeProvider>
                  )
                }
              </SessionGate>
            )}
          </ErrorReporterProvider>
        </ErrorBoundary>
      </AppearanceProvider>
    </QueryClientProvider>
  );
}
