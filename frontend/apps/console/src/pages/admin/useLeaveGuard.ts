import { App } from 'antd';
import { useEffect, useRef } from 'react';
import { useBlocker } from 'react-router';

import { useLabel } from '@supportx/ui';

/**
 * Leaving a settings page with unsaved changes asks first (QA6S-SHELL-05): a link, the menu or
 * the back button inside the app. Closing or reloading the tab is asked by `StickySaveBar`.
 */
export function useLeaveGuard(dirty: boolean): void {
  const t = useLabel();
  const { modal } = App.useApp();
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty && currentLocation.pathname !== nextLocation.pathname,
  );
  // One question per attempt: the effect runs again while the blocker stays blocked.
  const asking = useRef(false);
  useEffect(() => {
    if (blocker.state !== 'blocked' || asking.current) return;
    asking.current = true;
    modal.confirm({
      title: t('settings.leave_title'),
      content: t('settings.leave_body'),
      okText: t('settings.leave_ok'),
      cancelText: t('settings.leave_stay'),
      okButtonProps: { danger: true },
      onOk: () => {
        asking.current = false;
        blocker.proceed();
      },
      onCancel: () => {
        asking.current = false;
        blocker.reset();
      },
    });
  }, [blocker, modal, t]);
}

/**
 * The same guard as an element, for a page that only knows it has changes after its early
 * returns (hooks cannot follow those): render it beside the page's `StickySaveBar`.
 */
export function LeaveGuard({ dirty }: { dirty: boolean }): null {
  useLeaveGuard(dirty);
  return null;
}
