import { Button, Result } from 'antd';
import { useEffect, useMemo } from 'react';

import { useLabel } from '../appearance';
import { BrandedPage } from '../brand';
import {
  announceConfirmed,
  confirmedStatus,
  isAttempt,
  safeReturnTo,
  type ChannelFactory,
} from './confirmation';

export interface ConfirmedPageProps {
  /** For tests: the channel and the window's close/replace. */
  channel?: ChannelFactory;
  close?: () => void;
  replace?: (path: string) => void;
}

/**
 * Where a confirmation lands (REQ-SEC-027), outside the session gate, in both UIs. From the
 * pop-up (an attempt id): tell the opener and close. The opener's dialog sends the change again.
 * From a full-page confirmation (the pop-up was blocked): go straight back after "ok", otherwise
 * say what happened with a way back. The way back is always a path on this site (safeReturnTo).
 */
export function ConfirmedPage({
  channel,
  close = () => {
    window.close();
  },
  replace = (path) => {
    window.location.replace(path);
  },
}: ConfirmedPageProps) {
  const t = useLabel();
  const { status, attempt, back } = useMemo(() => {
    const query = new URLSearchParams(window.location.search);
    const id = query.get('attempt');
    return {
      status: confirmedStatus(query.get('status')),
      attempt: isAttempt(id) ? id : null,
      back: safeReturnTo(query.get('returnTo')),
    };
  }, []);

  useEffect(() => {
    if (attempt !== null) {
      announceConfirmed(status, attempt, channel);
      close(); // may be refused (the window was not opened by script); the page says so
    } else if (status === 'ok') {
      replace(back);
    }
    // Once, on landing.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: announce once
  }, []);

  const title =
    status === 'ok'
      ? t('reauth.done_ok')
      : status === 'unavailable'
        ? t('errors.reauth_unavailable')
        : t('reauth.done_failed');
  return (
    <BrandedPage>
      <div data-testid={`confirmed-${status}`}>
        <Result
          status={status === 'ok' ? 'success' : 'warning'}
          title={title}
          subTitle={attempt !== null ? t('reauth.close_window') : undefined}
          extra={
            <Button href={back} data-testid="confirmed-back">
              {t('reauth.back')}
            </Button>
          }
        />
      </div>
    </BrandedPage>
  );
}
