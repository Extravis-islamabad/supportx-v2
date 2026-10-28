import { Badge, Card, Col, Row, Space, Statistic, Typography } from 'antd';

import { useDashboards, useSession } from '@supportx/api-client';
import { useAccess, useLabel, useLicence } from '@supportx/ui';

import { ApiStatus } from './ApiStatus';
import { DashboardPage } from './dashboards/DashboardsPage';

/**
 * Landing page (REQ-DSH-001): who and where you are, then your home dashboard (your choice, your
 * role's, or the built-in one, REQ-DSH-002), live; then the plan and seat usage.
 */
export function HomePage() {
  const t = useLabel();
  const session = useSession().data;
  const { can } = useAccess();
  const dashboards = useDashboards(can('reports.view'));
  const home = dashboards.data?.home;
  const { entitlements } = useLicence();
  const seats = entitlements?.limits.find((limit) => limit.key === 'technicians');

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div>
        <Typography.Title level={1}>
          {t('home.title', { name: session?.user.display_name ?? '' })}
        </Typography.Title>
        <Space>
          <Typography.Text type="secondary">
            {t('home.subtitle', { tenant: session?.tenant.name ?? '' })}
          </Typography.Text>
          <ApiStatus />
        </Space>
      </div>
      {home !== undefined && <DashboardPage dashboardRef={home} home />}
      {entitlements !== null && (
        <Row gutter={[16, 16]}>
          <Col xs={24} md={8}>
            <Card>
              <Statistic
                title={t('home.plan')}
                value={
                  entitlements.edition === null
                    ? t('entitlement_state.invalid')
                    : t(`edition.${entitlements.edition}`)
                }
              />
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card>
              <Typography.Text type="secondary">{t('home.plan_state')}</Typography.Text>
              <div style={{ marginTop: 8 }}>
                <Badge
                  data-testid="licence-state"
                  status={entitlements.writable ? 'success' : 'error'}
                  text={t(`entitlement_state.${entitlements.state}`)}
                />
              </div>
            </Card>
          </Col>
          {seats?.used !== null && seats?.used !== undefined && (
            <Col xs={24} md={8}>
              <Card>
                <Typography.Text type="secondary">{t('home.technician_seats')}</Typography.Text>
                <div style={{ marginTop: 8 }}>
                  <Typography.Text strong>
                    {seats.limit === null
                      ? t('home.seats_unlimited', { used: seats.used })
                      : t('home.seats_used', { used: seats.used, limit: seats.limit })}
                  </Typography.Text>
                </div>
              </Card>
            </Col>
          )}
        </Row>
      )}
    </Space>
  );
}
