import { QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { RouterProvider } from 'react-router';

import { RealtimeProvider } from '@supportx/realtime';

import {
  AddressBranding,
  AppearanceProvider,
  createQueryClient,
  DevSignInPage,
  ErrorBoundary,
  ErrorReporterProvider,
  isDevSignIn,
  LicenceProvider,
  PASSWORD_RESET_PATH,
  PasswordResetPage,
  SessionGate,
  TenantBranding,
  type SessionGateProps,
} from '@supportx/ui';

import { PublicApprovalPage } from './pages/approvals/PublicApprovalPage';

import { createRouter } from './router';

export interface AppProps {
  /** For tests: replaces the browser navigation to the login page. */
  navigate?: SessionGateProps['navigate'];
}

/** The public approval page, wherever the portal is served (`/approve`, `/portal/approve`). */
function isPublicApproval(pathname: string): boolean {
  return pathname.replace(/\/$/, '').endsWith('/approve');
}

export function App({ navigate }: AppProps) {
  const [queryClient] = useState(createQueryClient);
  const [router] = useState(createRouter);
  return (
    <QueryClientProvider client={queryClient}>
      <AppearanceProvider>
        <AddressBranding />
        <ErrorBoundary>
          <ErrorReporterProvider>
            {window.location.pathname === PASSWORD_RESET_PATH ? (
              // "Forgot password?" is for people who cannot sign in (WP-039 session 2).
              <PasswordResetPage app="portal" />
            ) : isDevSignIn(window.location.pathname) ? (
              // Dev-only quick sign-in (D-151): the API answers 404 anywhere but the local stack.
              <DevSignInPage />
            ) : isPublicApproval(window.location.pathname) ? (
              // An e-mailed approval link without sign-in (D-132): its own page, no session.
              <PublicApprovalPage />
            ) : (
              <SessionGate app="portal" navigate={navigate}>
                {(session) => (
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
