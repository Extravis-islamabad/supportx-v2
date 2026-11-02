import { Alert } from 'antd';

import { useEventDelivery } from '@supportx/api-client';
import { useAccess, useLabel } from '@supportx/ui';

const WORKERS = ['outbox_relay', 'event_consumers', 'realtime_fanout'] as const;

/**
 * Event delivery stalled (must-fix before the pilot, 2026-10-28): an event worker is down, cannot
 * reach the database or the message bus, or events wait too long. Shown to administrators
 * (`settings.manage`) while it lasts, naming the worker and why, so nobody is left guessing why
 * notifications or live updates are late. Nothing is lost: they go out once it recovers.
 */
export function EventDeliveryBanner() {
  const t = useLabel();
  const { can } = useAccess();
  const allowed = can('settings.manage');
  const readiness = useEventDelivery(allowed);
  const data = readiness.data;
  if (!allowed || data?.event_delivery !== 'stalled') return null;
  const causes = WORKERS.flatMap((name) => {
    const check = data.checks[name];
    if (check === undefined || check.status === 'ok') return [];
    return [`${t(`readiness_check.${name}`)}: ${t(`failure_reason.${check.reason ?? 'error'}`)}`];
  });
  if (data.checks.nats !== undefined && data.checks.nats.status !== 'ok') {
    causes.push(
      `${t('readiness_check.nats')}: ${t(`failure_reason.${data.checks.nats.reason ?? 'error'}`)}`,
    );
  }
  return (
    <Alert
      type="error"
      showIcon
      role="alert"
      data-testid="event-delivery-banner"
      message={t('event_delivery.stalled.title')}
      description={
        <>
          {t('event_delivery.stalled.body')}
          {causes.length > 0 && (
            <ul style={{ margin: '4px 0 0', paddingInlineStart: 20 }}>
              {causes.map((cause) => (
                <li key={cause}>{cause}</li>
              ))}
            </ul>
          )}
        </>
      }
    />
  );
}
