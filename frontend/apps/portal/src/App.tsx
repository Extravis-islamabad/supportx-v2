import { QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { RouterProvider } from 'react-router';

import { RealtimeProvider } from '@supportx/realtime';

import {
  AddressBranding,
  AppearanceProvider,
  ConfirmedPage,
  storedLocale,
  createQueryClient,
  DevSignInPage,
  ErrorBoundary,
  ErrorReporterProvider,
  isConfirmedPage,
  isDevSignIn,
  LicenceProvider,
  PASSWORD_RESET_PATH,
  InvitePage,
  isInvitePage,
  PasswordResetPage,
  SessionGate,
  TenantBranding,
  type SessionGateProps,
} from '@supportx/ui';

import { PublicApprovalPage } from './pages/approvals/PublicApprovalPage';
import { StopMailsPage } from './pages/StopMailsPage';

import { createRouter } from './router';

export interface AppProps {
  /** For tests: replaces the browser navigation to the login page. */
  navigate?: SessionGateProps['navigate'];
}

/** Stopping mails to an address kept informed, wherever the portal is served (WP-046a S6). */
function isStopMails(pathname: string): boolean {
  return pathname.replace(/\/$/, '').endsWith('/stop-mails');
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
      <AppearanceProvider initialLocale={storedLocale() ?? undefined}>
        <AddressBranding />
        <ErrorBoundary>
          <ErrorReporterProvider>
            {isConfirmedPage(window.location.pathname) ? (
              // A confirmation's landing (REQ-SEC-027): it tells the opener and closes. Outside
              // the session gate, so it never starts a sign-in of its own.
              <ConfirmedPage />
            ) : window.location.pathname === PASSWORD_RESET_PATH ? (
              // "Forgot password?" is for people who cannot sign in (WP-039 session 2).
              <PasswordResetPage app="portal" />
            ) : isInvitePage(window.location.pathname) ? (
              // A copied invite link (REQ-SEC-021): its own page, no session; nobody signs in here.
              <InvitePage app="portal" />
            ) : isDevSignIn(window.location.pathname) ? (
              // Dev-only quick sign-in (D-151): the API answers 404 anywhere but the local stack.
              <DevSignInPage />
            ) : isStopMails(window.location.pathname) ? (
              // A stop-these-mails link from a mail to someone kept informed: no session.
              <StopMailsPage />
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
