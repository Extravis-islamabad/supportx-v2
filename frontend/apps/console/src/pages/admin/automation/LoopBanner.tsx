import { Alert } from 'antd';
import { Link } from 'react-router';

import { useLoopStops } from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { useAccess, useLabel } from '@supportx/ui';

/**
 * Loops the automation guard stopped in the last day (REQ-RUL-028 AC3): admins are told here
 * until in-app notifications arrive (WP-023). Live through `automation.changed`.
 */
export function LoopBanner() {
  const t = useLabel();
  const listFormat = useListFormat();
  const { can } = useAccess();
  const allowed = can('automation.view');
  const stops = useLoopStops(allowed);
  const latest = stops.data?.[0];
  if (!allowed || latest === undefined) return null;
  return (
    <Alert
      type="warning"
      showIcon
      data-testid="loop-banner"
      message={t('automation.loop.banner', { count: stops.data?.length ?? 0 })}
      description={
        <>
          {t(`automation.loop.${latest.cap}`, {
            triggers: listFormat(latest.triggers, 'conjunction'),
          })}{' '}
          <Link to={`/incidents/${latest.record_id}`} style={{ textDecoration: 'underline' }}>
            {t('automation.loop.open')}
          </Link>{' '}
          <Link to="/admin/automation/triggers" style={{ textDecoration: 'underline' }}>
            {t('automation.loop.open_triggers')}
          </Link>
        </>
      }
    />
  );
}
