import { Grid, Switch, Tooltip } from 'antd';

import { useAvailability, useSetAvailability } from '@supportx/api-client';
import { reportError, useLabel } from '@supportx/ui';

/**
 * A technician's Available / Away switch in the header (WP-029, REQ-ASG-006, D-097): Away
 * people are never auto-assigned. Admins set it for others on the person's page.
 */
export function AvailabilitySwitch({ userId }: { userId: string }) {
  const t = useLabel();
  const current = useAvailability([userId]);
  const set = useSetAvailability();
  // Below 1200 px: no words inside the switch, so the header never scrolls sideways (the top
  // layout's menu takes the room up to there; stack smoke at 768 px).
  const wide = Grid.useBreakpoint().xl === true;
  const state = current.data?.find((a) => a.user_id === userId)?.state ?? 'available';
  return (
    <Tooltip title={t('automation.availability.help')}>
      <Switch
        checked={state === 'available'}
        loading={current.isPending || set.isPending}
        size={wide ? 'default' : 'small'}
        checkedChildren={wide ? t('availability.available') : undefined}
        unCheckedChildren={wide ? t('availability.away') : undefined}
        aria-label={t('automation.availability.label')}
        onChange={(on) => {
          set.mutate({ userId, state: on ? 'available' : 'away' }, { onError: reportError });
        }}
        data-testid="availability-switch"
      />
    </Tooltip>
  );
}
