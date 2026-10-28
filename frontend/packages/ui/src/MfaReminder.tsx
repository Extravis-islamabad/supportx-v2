import { Alert, Button } from 'antd';

import { accountActionUrl, useSession } from '@supportx/api-client';

import { useLabel } from './appearance';
import { useDateTime } from './dates';

/**
 * While MFA is required and not set up (WP-039 session 3, REQ-SEC-024): when it is due, and a
 * button to set it up now on the sign-in service's page. After the date, the sign-in itself
 * makes the person set it up, so this is a reminder, never a gate.
 */
export function MfaReminder() {
  const t = useLabel();
  const dates = useDateTime();
  const due = useSession().data?.mfa_due_at;
  if (due === undefined || due === null) return null;
  return (
    <Alert
      type="warning"
      showIcon
      banner
      data-testid="mfa-reminder"
      message={t('account.mfa.reminder', { date: dates.format(due) })}
      action={
        <Button
          size="small"
          href={accountActionUrl('mfa', window.location.pathname)}
          data-testid="mfa-reminder-set-up"
        >
          {t('account.mfa.set_up')}
        </Button>
      }
    />
  );
}
