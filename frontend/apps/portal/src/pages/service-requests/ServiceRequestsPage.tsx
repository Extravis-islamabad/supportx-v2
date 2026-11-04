import { useQueryClient } from '@tanstack/react-query';
import { Card, Flex, List, Segmented, Typography } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import { portalRequestKeys, usePortalRequests, type PortalState } from '@supportx/api-client';
import { usePersonalChannel } from '@supportx/realtime';
import { EmptyText, reportError, useDateTime, useLabel } from '@supportx/ui';

import { PortalStatusTag } from '../requests/PortalStatusTag';

const STATES: (PortalState | 'all')[] = ['open', 'closed', 'all'];

/**
 * The requester's service requests (WP-030 D9, REQ-SR-062): plain statuses (waiting for
 * approval, not approved…), open or closed. Live: a change to one of their records reaches
 * their own channel and the list refetches through the API, where the reach rules apply again.
 */
export function ServiceRequestsPage() {
  const t = useLabel();
  const { relative, format } = useDateTime();
  const queryClient = useQueryClient();
  const [state, setState] = useState<PortalState | 'all'>('open');
  const list = usePortalRequests(state === 'all' ? undefined : state);
  usePersonalChannel((event) => {
    if (event.type === 'work_items.changed') {
      void queryClient.invalidateQueries({ queryKey: portalRequestKeys.all });
    }
  });
  if (list.error) reportError(list.error);
  const items = list.data?.items ?? [];
  return (
    <Flex vertical gap={16}>
      <Typography.Title level={1} style={{ margin: 0 }}>
        {t('portal.service_requests.title')}
      </Typography.Title>
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
        data-testid="portal-service-requests-state"
      />
      <List
        loading={list.isLoading}
        dataSource={items}
        locale={{ emptyText: <EmptyText>{t('portal.requests.empty')}</EmptyText> }}
        renderItem={(r) => (
          <List.Item key={r.id}>
            <Card style={{ width: '100%' }} data-testid={`portal-service-request-${r.display_id}`}>
              <Flex justify="space-between" align="center" gap={12} wrap>
                <Link to={`/service-requests/${r.id}`}>
                  <span dir="ltr">{r.display_id}</span> · <bdi>{r.subject}</bdi>
                </Link>
                <PortalStatusTag status={r.portal_status} />
              </Flex>
              <Typography.Text type="secondary" title={format(r.updated_at)}>
                {t('portal.requests.updated', { when: relative(r.updated_at) })}
              </Typography.Text>
            </Card>
          </List.Item>
        )}
      />
    </Flex>
  );
}
