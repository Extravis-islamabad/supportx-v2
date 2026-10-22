import { Button, Flex, Result, Spin } from 'antd';
import { useEffect, type ReactNode } from 'react';

import { loginUrl, useSession, type App, type MeResponse } from '@supportx/api-client';
import { label, LOCALES, type Locale } from '@supportx/labels';

import { useAppearance, useLabel } from './appearance';

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
  const loginError = loginErrorCode();

  useEffect(() => {
    if (session.isSuccess && me === null && loginError === null) {
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
    );
  }
  if (session.isError) {
    return (
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
    );
  }
  if (me === undefined || me === null) {
    return (
      <Flex justify="center" align="center" style={{ minHeight: '100vh' }}>
        <Spin tip={t(me === null ? 'auth.redirecting_to_login' : 'auth.checking_session')}>
          <div style={{ padding: 48 }} />
        </Spin>
      </Flex>
    );
  }
  return <>{children(me)}</>;
}
