import {
  Alert,
  Card,
  Descriptions,
  Flex,
  Progress,
  Skeleton,
  Space,
  Table,
  Typography,
} from 'antd';

import { type Entitlements, useEntitlements } from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import { NoAccess, ToneTag, type Tone, useAccess, useDateTime, useLabel } from '@supportx/ui';

// WP-042 (REQ-ADM-109): Admin › Licence and plan. Everything comes from the entitlement interface
// (GET /entitlements); the licence file is never read here. Usage is live: adding or removing a
// technician sends `entitlements.usage_changed`, a plan change `entitlements.changed`.

type Limit = Entitlements['limits'][number];

const STATE_TONE: Record<Entitlements['state'], Tone> = {
  active: 'success',
  grace: 'warning',
  read_only: 'error',
  invalid: 'error',
};

function UsageCell({ limit }: { limit: Limit }) {
  const t = useLabel();
  if (limit.limit === null) {
    return (
      <Typography.Text>
        {limit.used === null
          ? t('licence_page.unlimited')
          : t('licence_page.used_unlimited', { used: limit.used })}
      </Typography.Text>
    );
  }
  if (limit.used === null)
    return <Typography.Text>{t('licence_page.not_counted')}</Typography.Text>;
  const percent = Math.min(100, Math.round((limit.used / Math.max(limit.limit, 1)) * 100));
  return (
    <Space direction="vertical" size={2} style={{ width: '100%', minWidth: 180 }}>
      <Typography.Text>
        {t('licence_page.used_of', { used: limit.used, limit: limit.limit })}
      </Typography.Text>
      <Progress
        percent={percent}
        showInfo={false}
        size="small"
        status={percent >= 100 ? 'exception' : 'normal'}
        aria-label={t('licence_page.used_of', { used: limit.used, limit: limit.limit })}
      />
    </Space>
  );
}

export function LicencePage() {
  const t = useLabel();
  const dates = useDateTime();
  const { can } = useAccess();
  const plan = useEntitlements(can('licence.manage'));
  useTenantChannel((message) => {
    if (message.type === 'entitlements.usage_changed') void plan.refetch();
  });

  if (!can('licence.manage')) return <NoAccess titleKey="nav.admin_licence" />;
  if (plan.data === undefined) return <Skeleton active />;
  const data = plan.data;
  const term = data.term;

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }} data-testid="licence-page">
      <Card title={t('licence_page.plan')}>
        <Descriptions column={{ xs: 1, md: 2 }} size="small">
          <Descriptions.Item label={t('licence_page.edition')}>
            <span data-testid="licence-edition">
              {data.edition === null ? t('licence_page.no_edition') : t(`edition.${data.edition}`)}
            </span>
          </Descriptions.Item>
          <Descriptions.Item label={t('licence_page.state')}>
            <ToneTag tone={STATE_TONE[data.state]}>{t(`entitlement_state.${data.state}`)}</ToneTag>
          </Descriptions.Item>
          {term !== null && (
            <>
              <Descriptions.Item label={t('licence_page.starts')}>
                {dates.format(term.starts_at)}
              </Descriptions.Item>
              <Descriptions.Item label={t('licence_page.expires')}>
                {term.expires_at === null
                  ? t('licence_page.no_end')
                  : dates.format(term.expires_at)}
              </Descriptions.Item>
              <Descriptions.Item label={t('licence_page.maintenance')}>
                {term.maintenance_until === null
                  ? t('licence_page.no_end')
                  : dates.format(term.maintenance_until)}
              </Descriptions.Item>
              <Descriptions.Item label={t('licence_page.grace_days')}>
                {t('licence_page.days', { count: term.grace_days })}
              </Descriptions.Item>
            </>
          )}
        </Descriptions>
        {data.state_reason !== null && (
          <Alert
            type={data.state === 'grace' ? 'warning' : 'error'}
            showIcon
            style={{ marginTop: 12 }}
            message={t(`entitlement_reason.${data.state_reason}`)}
            description={
              data.grace_ends_at === null
                ? undefined
                : t('licence_page.grace_until', { when: dates.format(data.grace_ends_at) })
            }
          />
        )}
      </Card>
      <Card title={t('licence_page.limits')}>
        <Table<Limit>
          rowKey="key"
          size="small"
          pagination={false}
          dataSource={data.limits}
          data-testid="licence-limits"
          columns={[
            {
              title: t('licence_page.limit'),
              key: 'key',
              render: (_, limit) => t(`limit.${limit.key}`),
            },
            {
              title: t('licence_page.usage'),
              key: 'usage',
              render: (_, limit) => <UsageCell limit={limit} />,
            },
          ]}
        />
      </Card>
      <Card title={t('licence_page.features')}>
        <Flex wrap gap={6} data-testid="licence-features">
          {data.features.map((feature) => (
            <ToneTag key={feature} tone="default">
              {t(`feature.${feature}`)}
            </ToneTag>
          ))}
        </Flex>
      </Card>
      <Typography.Paragraph type="secondary">{t('licence_page.upgrade')}</Typography.Paragraph>
    </Space>
  );
}
