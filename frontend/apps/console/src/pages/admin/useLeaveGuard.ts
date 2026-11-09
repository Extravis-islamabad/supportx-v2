import { App } from 'antd';
import { useEffect } from 'react';
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
  useEffect(() => {
    if (blocker.state !== 'blocked') return;
    modal.confirm({
      title: t('settings.leave_title'),
      content: t('settings.leave_body'),
      okText: t('settings.leave_ok'),
      cancelText: t('settings.leave_stay'),
      okButtonProps: { danger: true },
      onOk: () => {
        blocker.proceed();
      },
      onCancel: () => {
        blocker.reset();
      },
    });
  }, [blocker, modal, t]);
}
