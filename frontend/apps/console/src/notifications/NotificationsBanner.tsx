import { Alert } from 'antd';

import { useNotificationStatus } from '@supportx/api-client';
import { useAccess, useLabel } from '@supportx/ui';

/**
 * E-mail notifications waiting because outgoing mail is not set up (REQ-NTF-020 AC3, never
 * silent): shown to holders of `notifications.manage` while any wait. In-app entries still go
 * out; the waiting e-mails are sent once mail works.
 */
export function NotificationsBanner() {
  const t = useLabel();
  const { can } = useAccess();
  const allowed = can('notifications.manage');
  const status = useNotificationStatus(allowed);
  const waiting = status.data?.waiting ?? 0;
  if (!allowed || waiting === 0) return null;
  return (
    <Alert
      type="warning"
      showIcon
      role="alert"
      data-testid="notifications-banner"
      message={t('notifications.banner.title')}
      description={t(
        status.data?.mail_configured === true
          ? 'notifications.banner.sending'
          : 'notifications.banner.no_mail',
        { count: waiting },
      )}
    />
  );
}
