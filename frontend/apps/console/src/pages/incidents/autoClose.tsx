import { Typography } from 'antd';

import type { Incident, IncidentCatalogue } from '@supportx/api-client';
import { useDateTime, useLabel } from '@supportx/ui';

import { addBusinessDays } from './businessDays';

/**
 * While resolved and auto-close is on: when it will close, or that it waits until the requester
 * has been told (REQ-INC-096; never auto-closed for a requester who was not told, D-107).
 */
export function AutoCloseNote({
  item,
  catalogue,
}: {
  item: Incident;
  catalogue: IncidentCatalogue | undefined;
}) {
  const t = useLabel();
  const dates = useDateTime();
  const days = catalogue?.closure.auto_close_days ?? null;
  if (item.status_category !== 'resolved' || days === null) return null;
  return (
    <Typography.Text type="secondary" data-testid="inc-auto-close">
      {item.resolution_notified_at === null
        ? t('incidents.closing.auto_close_waits')
        : t('incidents.closing.auto_close_on', {
            date: dates.format(
              addBusinessDays(new Date(item.resolution_notified_at), days).toISOString(),
            ),
          })}
    </Typography.Text>
  );
}
