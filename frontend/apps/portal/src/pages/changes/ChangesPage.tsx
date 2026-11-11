import { useQueryClient } from '@tanstack/react-query';
import { Button, Card, Flex, List, Segmented, Space, Tag, Typography } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import { portalChangeKeys, usePortalChanges, type PortalState } from '@supportx/api-client';
import { usePersonalChannel } from '@supportx/realtime';
import { EmptyText, reportError, useDateTime, useLabel } from '@supportx/ui';

const STATES: (PortalState | 'all')[] = ['open', 'closed', 'all'];

/**
 * The requester's changes (WP-045d S4a, REQ-CHG-109): each one's stage and status, open or
 * closed. Live: a change to one of their records reaches their own channel and the list
 * refetches through the portal API, where the reach rules apply again.
 */
export function ChangesPage() {
  const t = useLabel();
  const { relative, format } = useDateTime();
  const queryClient = useQueryClient();
  const [state, setState] = useState<PortalState | 'all'>('open');
  const list = usePortalChanges(state === 'all' ? undefined : state);
  usePersonalChannel((event) => {
    if (event.type === 'work_items.changed') {
      void queryClient.invalidateQueries({ queryKey: portalChangeKeys.all });
    }
  });
  if (list.error) reportError(list.error);
  const items = list.data?.items ?? [];
  return (
    <Flex vertical gap={16}>
      <Flex justify="space-between" align="center" gap={12} wrap>
        <Typography.Title level={1} style={{ margin: 0 }}>
          {t('portal.changes.title')}
        </Typography.Title>
        <Link to="/changes/new" data-testid="portal-changes-raise">
          <Button type="primary">{t('portal.changes.raise')}</Button>
        </Link>
      </Flex>
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
        data-testid="portal-changes-state"
      />
      <List
        loading={list.isLoading}
        dataSource={items}
        locale={{ emptyText: <EmptyText>{t('portal.changes.empty')}</EmptyText> }}
        renderItem={(c) => (
          <List.Item key={c.id}>
            <Card style={{ width: '100%' }} data-testid={`portal-change-${c.display_id}`}>
              <Flex justify="space-between" align="center" gap={12} wrap>
                <Link to={`/changes/${c.id}`}>
                  <span dir="ltr">{c.display_id}</span> · <bdi>{c.subject}</bdi>
                </Link>
                <Space wrap size={4}>
                  {c.stage != null && <Tag>{t(`work_item_stage.${c.stage}`)}</Tag>}
                  <Tag color="blue">{t(`work_item_status.${c.status}`)}</Tag>
                </Space>
              </Flex>
              <Typography.Text type="secondary" title={format(c.updated_at)}>
                {t('portal.requests.updated', { when: relative(c.updated_at) })}
              </Typography.Text>
            </Card>
          </List.Item>
        )}
      />
    </Flex>
  );
}
