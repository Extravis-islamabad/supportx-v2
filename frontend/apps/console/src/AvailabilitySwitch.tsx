import { Card, Grid, Space, Switch, Tooltip, Typography } from 'antd';

import { useAvailability, useSetAvailability } from '@supportx/api-client';
import { reportError, useLabel } from '@supportx/ui';

/**
 * A technician's Available / Away switch (WP-029, REQ-ASG-006, D-097): Away people are never
 * auto-assigned. In the header only from 1200 px, where it fits beside the top layout's menu
 * (stack smoke: the header overflowed at 768 px); always on My profile. Admins may set it for
 * someone else through the API (`users.manage`).
 */
export function AvailabilitySwitch({ userId }: { userId: string }) {
  const wide = Grid.useBreakpoint().xl === true;
  if (!wide) return null;
  return <Toggle userId={userId} testId="availability-switch" />;
}

/** The same switch on My profile, with what it means. */
export function AvailabilityCard({ userId }: { userId: string }) {
  const t = useLabel();
  return (
    <Card title={t('automation.availability.label')} data-testid="availability-card">
      <Space direction="vertical">
        <Toggle userId={userId} testId="availability-profile-switch" />
        <Typography.Text type="secondary">{t('automation.availability.help')}</Typography.Text>
      </Space>
    </Card>
  );
}

function Toggle({ userId, testId }: { userId: string; testId: string }) {
  const t = useLabel();
  const current = useAvailability([userId]);
  const set = useSetAvailability();
  const state = current.data?.find((a) => a.user_id === userId)?.state ?? 'available';
  return (
    <Tooltip title={t('automation.availability.help')}>
      <Switch
        checked={state === 'available'}
        loading={current.isPending || set.isPending}
        checkedChildren={t('availability.available')}
        unCheckedChildren={t('availability.away')}
        aria-label={t('automation.availability.label')}
        onChange={(on) => {
          set.mutate({ userId, state: on ? 'available' : 'away' }, { onError: reportError });
        }}
        data-testid={testId}
      />
    </Tooltip>
  );
}
