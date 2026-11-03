import { PlusOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Card, Flex, Input, List, Segmented, Select, Typography } from 'antd';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  portalKeys,
  usePortalIncidents,
  type PortalReach,
  type PortalState,
} from '@supportx/api-client';
import { usePersonalChannel } from '@supportx/realtime';
import { EmptyText, reportError, useDateTime, useLabel } from '@supportx/ui';

import { PortalStatusTag } from './PortalStatusTag';

const STATES: (PortalState | 'all')[] = ['open', 'closed', 'all'];
const WIDER: PortalReach[] = ['reports', 'department', 'site', 'all'];

/**
 * "My requests" (REQ-PRT-007): the person's incidents, open or closed, searchable, newest change
 * first. A wider reach they hold (direct reports, department…) is a filter of its own. Rows stay
 * current with no reload: any change to one of their records reaches their own channel (ids
 * only) and the list refetches through the API, where the reach rules apply again.
 */
export function RequestsPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const { relative, format } = useDateTime();
  const queryClient = useQueryClient();
  const [state, setState] = useState<PortalState | 'all'>('open');
  const [reach, setReach] = useState<PortalReach | undefined>(undefined);
  const [search, setSearch] = useState('');
  const page = usePortalIncidents({
    state: state === 'all' ? undefined : state,
    reach,
    q: search.trim() === '' ? undefined : search.trim(),
  });
  usePersonalChannel((event) => {
    if (event.type === 'work_items.changed') {
      void queryClient.invalidateQueries({ queryKey: [...portalKeys.all, 'list'] });
    }
  });
  if (page.error) reportError(page.error);
  const items = page.data?.items ?? [];
  const wider = items.some((i) => i.reach !== 'own') || reach !== undefined;

  return (
    <Flex vertical gap={16}>
      <Flex align="center" justify="space-between" gap={12} wrap>
        <Typography.Title level={1} style={{ margin: 0 }}>
          {t('nav.my_requests')}
        </Typography.Title>
        <Button
          type="primary"
          size="large"
          icon={<PlusOutlined />}
          onClick={() => void navigate('/requests/new')}
          data-testid="portal-report"
        >
          {t('portal.report.open')}
        </Button>
      </Flex>
      <Flex gap={8} wrap align="center">
        <Segmented
          value={state}
          onChange={(value) => {
            setState(value);
          }}
          options={STATES.map((s) => ({
            value: s,
            label: s === 'all' ? t('portal.requests.all_states') : t(`portal_state.${s}`),
          }))}
          aria-label={t('portal.requests.state')}
          data-testid="portal-requests-state"
        />
        {wider && (
          <Select
            allowClear
            value={reach}
            onChange={(value: PortalReach | undefined) => {
              setReach(value);
            }}
            placeholder={t('portal.requests.whose')}
            aria-label={t('portal.requests.whose')}
            style={{ minWidth: 180 }}
            options={['own' as const, ...WIDER].map((r) => ({
              value: r,
              label: t(`portal_reach.${r}`),
            }))}
            data-testid="portal-requests-reach"
          />
        )}
        <Input.Search
          allowClear
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
          }}
          placeholder={t('portal.requests.search')}
          aria-label={t('portal.requests.search')}
          style={{ flex: '1 1 220px', maxWidth: 360 }}
          data-testid="portal-requests-search"
        />
      </Flex>
      <List
        loading={page.isLoading}
        dataSource={items}
        locale={{ emptyText: <EmptyText>{t('portal.requests.empty')}</EmptyText> }}
        data-testid="portal-requests"
        renderItem={(item) => (
          <List.Item key={item.id} style={{ paddingInline: 0 }}>
            <Card
              size="small"
              style={{ width: '100%' }}
              data-testid={`portal-request-${item.display_id}`}
            >
              <Flex vertical gap={4}>
                <Flex justify="space-between" gap={8} wrap align="center">
                  <Link
                    to={`/requests/${item.id}`}
                    style={{
                      fontWeight: 600,
                      minHeight: 44,
                      display: 'inline-flex',
                      alignItems: 'center',
                    }}
                  >
                    <span dir="ltr">{item.display_id}</span>
                    <span style={{ marginInlineStart: 8 }}>{item.subject}</span>
                  </Link>
                  <PortalStatusTag status={item.portal_status} />
                </Flex>
                <Typography.Text type="secondary">
                  <time dateTime={item.updated_at} title={format(item.updated_at)}>
                    {t('portal.requests.updated', { when: relative(item.updated_at) })}
                  </time>
                  {item.reach !== 'own' && <> · {t(`portal_reach.${item.reach}`)}</>}
                </Typography.Text>
              </Flex>
            </Card>
          </List.Item>
        )}
      />
    </Flex>
  );
}
