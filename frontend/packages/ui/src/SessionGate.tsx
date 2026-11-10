import { Button, Flex, Result, Spin } from 'antd';
import { useEffect, type ReactNode } from 'react';

import {
  loginUrl,
  sessionRefusalCode,
  setClientApp,
  setPreferredTimeZone,
  useSession,
  type App,
  type MeResponse,
} from '@supportx/api-client';
import { label, LOCALES, type Locale } from '@supportx/labels';

import { useAppearance, useLabel } from './appearance';
import { BrandedPage, BrandLogo } from './brand';
import { IdleWatcher } from './IdleWatcher';

const CONSOLE_REQUESTER_ONLY = 'console_requester_only';
/** The portal home's query when the console sent a requester there (it says why). */
export const FROM_CONSOLE = 'from=console';

export interface SessionGateProps {
  app: App;
  children: (session: MeResponse) => ReactNode;
  /** Replaceable for tests; defaults to a real browser navigation. */
  navigate?: (url: string) => void;
}

function isLocale(value: string): value is Locale {
  return (LOCALES as readonly string[]).includes(value);
}

const defaultNavigate = (url: string): void => {
  window.location.assign(url);
};

/** `?auth_error=<code>` set by the BFF when a browser login failed (e.g. no organization). */
function loginErrorCode(): string | null {
  const code = new URLSearchParams(window.location.search).get('auth_error');
  return code !== null && /^[a-z_]{1,64}$/.test(code) ? code : null;
}

/**
 * Renders its children only for a logged-in user. Without a session the browser goes to the
 * BFF login (which sends it to Keycloak and back to the same page). The UI language, and with
 * it the text direction, follows the user's locale from the session.
 */
export function SessionGate({ app, children, navigate = defaultNavigate }: SessionGateProps) {
  const t = useLabel();
  const { locale, setLocale } = useAppearance();
  const session = useSession();
  const me = session.data;
  const userLocale = me?.user.locale;
  const userZone = me?.user.time_zone ?? null;
  const loginError = loginErrorCode();

  // Every call says which app made it (history shows "UI") and in which time zone the user
  // lives ("today" in filters): the profile's zone, else the browser's.
  useEffect(() => {
    setClientApp(app);
  }, [app]);
  useEffect(() => {
    setPreferredTimeZone(userZone);
  }, [userZone]);

  useEffect(() => {
    if (session.isSuccess && me === null && loginError === null) {
      // A requester-only person on the console goes to the portal, which signs them in on
      // Keycloak's own session and says why (D-129, QA10), never to a password page.
      if (app === 'console' && sessionRefusalCode() === CONSOLE_REQUESTER_ONLY) {
        navigate(loginUrl('portal', `/?${FROM_CONSOLE}`));
        return;
      }
      const here = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      navigate(loginUrl(app, here));
    }
  }, [session.isSuccess, me, app, navigate, loginError]);

  useEffect(() => {
    if (userLocale !== undefined && isLocale(userLocale)) {
      setLocale(userLocale);
    }
    // setLocale is recreated with the appearance context; only a new user locale should apply.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: apply once per locale
  }, [userLocale]);

  if (loginError !== null && !me) {
    // A failed login: explain it (translated) instead of bouncing straight back to Keycloak.
    return (
      <BrandedPage>
        <Result
          status="403"
          title={label(`errors.${loginError}`, locale)}
          extra={
            <Button
              type="primary"
              onClick={() => {
                navigate(loginUrl(app, '/'));
              }}
            >
              {t('auth.sign_in_again')}
            </Button>
          }
        />
      </BrandedPage>
    );
  }
  if (session.isError) {
    return (
      <BrandedPage>
        <Result
          status="warning"
          title={t('auth.session_error')}
          extra={
            <Button
              onClick={() => {
                void session.refetch();
              }}
            >
              {t('auth.retry')}
            </Button>
          }
        />
      </BrandedPage>
    );
  }
  if (me === undefined || me === null) {
    return (
      <Flex vertical justify="center" align="center" gap={24} style={{ minHeight: '100vh' }}>
        <BrandLogo height={40} />
        <Spin tip={t(me === null ? 'auth.redirecting_to_login' : 'auth.checking_session')}>
          <div style={{ padding: 48 }} />
        </Spin>
      </Flex>
    );
  }
  return (
    <>
      {children(me)}
      {me.idle_timeout_seconds != null && <IdleWatcher idleSeconds={me.idle_timeout_seconds} />}
    </>
  );
}
