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
  return <Pill userId={userId} />;
}

// The header's pill (UI pass 2): green "Available" or grey "Away", a switch for assistive tech.
// Measured: #067647 on #ECFDF3 5.4:1, #475467 on #F2F4F7 7.0:1.
const PILL = {
  available: { bg: '#ECFDF3', border: '#ABEFC6', fg: '#067647', dot: '#17B26A' },
  away: { bg: '#F2F4F7', border: '#D5D8DF', fg: '#475467', dot: '#98A2B3' },
} as const;

function Pill({ userId }: { userId: string }) {
  const t = useLabel();
  const current = useAvailability([userId]);
  const set = useSetAvailability();
  const state = current.data?.find((a) => a.user_id === userId)?.state ?? 'available';
  const on = state === 'available';
  const look = on ? PILL.available : PILL.away;
  return (
    <Tooltip title={t('automation.availability.help')}>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={t('automation.availability.label')}
        disabled={current.isPending || set.isPending}
        onClick={() => {
          set.mutate({ userId, state: on ? 'away' : 'available' }, { onError: reportError });
        }}
        data-testid="availability-switch"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          height: 32,
          paddingInline: 12,
          borderRadius: 999,
          border: `1px solid ${look.border}`,
          background: look.bg,
          color: look.fg,
          font: 'inherit',
          fontSize: 12,
          fontWeight: 600,
          cursor: 'pointer',
          whiteSpace: 'nowrap',
        }}
      >
        <span
          aria-hidden
          style={{ width: 8, height: 8, borderRadius: '50%', background: look.dot }}
        />
        {t(on ? 'availability.available' : 'availability.away')}
      </button>
    </Tooltip>
  );
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
