import { Button, Modal, Typography } from 'antd';
import { useEffect, useRef, useState } from 'react';

import { fetchMe, useLogout } from '@supportx/api-client';

import { useLabel } from './appearance';

/** Appendix A: the warning comes 2 minutes before the idle timeout. */
export const WARN_SECONDS = 120;
const ACTIVITY = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const;
/** Activity tells the server at most this often (any request keeps the session alive). */
const TOUCH_EVERY_MS = 60_000;

function mmss(seconds: number): string {
  const whole = Math.max(0, Math.ceil(seconds));
  return `${String(Math.floor(whole / 60))}:${String(whole % 60).padStart(2, '0')}`;
}

/**
 * Idle timeout on screen (WP-039 session 3, REQ-SEC-029 AC1). The server signs a session out
 * after the tenant's idle time without requests; live updates make requests on their own, so the
 * person's activity is what counts here. Two minutes before the limit a dialog asks whether to
 * stay; staying (or any activity) tells the server, and at the limit the person is signed out
 * here. Unsaved form input is kept by the forms themselves (`useKeptDraft`) and comes back after
 * signing in again (AC2).
 */
export function IdleWatcher({ idleSeconds }: { idleSeconds: number }) {
  const t = useLabel();
  const logout = useLogout();
  // A new function each render: the watch must not restart (and reset the clock) because of it.
  const signOut = useRef(logout);
  useEffect(() => {
    signOut.current = logout;
  }, [logout]);
  const lastActivity = useRef(0); // set when the watch starts (no clock during render)
  const lastTouch = useRef(0);
  const [remaining, setRemaining] = useState<number | null>(null);

  useEffect(() => {
    lastActivity.current = Date.now();
    lastTouch.current = Date.now();
    const active = () => {
      const now = Date.now();
      lastActivity.current = now;
      if (now - lastTouch.current >= TOUCH_EVERY_MS) {
        lastTouch.current = now;
        void fetchMe().catch(() => undefined); // the session gate reacts to an ended session
      }
    };
    for (const event of ACTIVITY) window.addEventListener(event, active, { passive: true });
    const timer = window.setInterval(() => {
      const left = idleSeconds - (Date.now() - lastActivity.current) / 1000;
      if (left <= 0) {
        window.clearInterval(timer);
        void signOut.current().catch(() => undefined);
        return;
      }
      setRemaining(left <= WARN_SECONDS ? left : null);
    }, 1000);
    return () => {
      for (const event of ACTIVITY) window.removeEventListener(event, active);
      window.clearInterval(timer);
    };
  }, [idleSeconds]);

  const stay = () => {
    lastActivity.current = Date.now();
    lastTouch.current = Date.now();
    setRemaining(null);
    void fetchMe().catch(() => undefined);
  };

  return (
    <Modal
      open={remaining !== null}
      title={t('session.idle.title')}
      closable={false}
      maskClosable={false}
      data-testid="idle-warning"
      footer={[
        <Button
          key="out"
          onClick={() => {
            void logout().catch(() => undefined);
          }}
          data-testid="idle-sign-out"
        >
          {t('session.idle.sign_out')}
        </Button>,
        <Button key="stay" type="primary" onClick={stay} data-testid="idle-stay">
          {t('session.idle.stay')}
        </Button>,
      ]}
    >
      <Typography.Paragraph>
        {t('session.idle.body', { time: mmss(remaining ?? 0) })}
      </Typography.Paragraph>
    </Modal>
  );
}
