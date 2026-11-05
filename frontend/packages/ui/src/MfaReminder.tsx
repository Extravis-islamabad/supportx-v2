import { Alert, Button, Grid } from 'antd';

import { accountActionUrl, useSession } from '@supportx/api-client';

import { useLabel } from './appearance';
import { useDateTime } from './dates';

/**
 * While MFA is required and not set up (WP-039 session 3, REQ-SEC-024): when it is due, and a
 * button to set it up now on the sign-in service's page. After the date, the sign-in itself
 * makes the person set it up, so this is a reminder, never a gate.
 *
 * On phones it is one line with a short "Set up" (QA 2026-11-05 V2: the full sentence wrapped into
 * a tall block); the whole sentence stays its accessible description and tooltip.
 */
export function MfaReminder() {
  const t = useLabel();
  const dates = useDateTime();
  const due = useSession().data?.mfa_due_at;
  const screens = Grid.useBreakpoint();
  const phone = screens.md === false && (screens.xs === true || screens.sm === true);
  if (due === undefined || due === null) return null;
  const full = t('account.mfa.reminder', { date: dates.format(due) });
  return (
    <Alert
      type="warning"
      showIcon
      banner
      data-testid="mfa-reminder"
      message={
        phone ? (
          <span
            title={full}
            style={{
              display: 'block',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {t('account.mfa.reminder_short', { date: dates.format(due) })}
          </span>
        ) : (
          full
        )
      }
      action={
        <Button
          size="small"
          href={accountActionUrl('mfa', window.location.pathname)}
          aria-label={phone ? t('account.mfa.set_up') : undefined}
          data-testid="mfa-reminder-set-up"
        >
          {phone ? t('account.mfa.set_up_short') : t('account.mfa.set_up')}
        </Button>
      }
    />
  );
}
