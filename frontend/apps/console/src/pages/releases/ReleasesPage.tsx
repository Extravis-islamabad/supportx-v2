import { PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Flex, Table } from 'antd';
import { useNavigate } from 'react-router';

import { releaseKeys, useReleases, type ReleaseListItem } from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import {
  EmptyText,
  PageHeader,
  ToneTag,
  WriteButton,
  reportError,
  useAccess,
  useDateTime,
  useLabel,
} from '@supportx/ui';

import { EMERGENCY_PATH, stageName, statusName } from './labels';

/**
 * The releases list (WP-058a s6): number, title, stage and status, the emergency flag
 * (REQ-REL-012 AC3), live on the type's list channel (a new release appears at once, REQ-REL-007
 * AC3). On a phone the table scrolls in a region a keyboard can reach.
 */
export function ReleasesPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { can } = useAccess();
  const { format } = useDateTime();
  const list = useReleases({});
  useListChannel('releases', () => {
    void queryClient.invalidateQueries({ queryKey: [...releaseKeys.all, 'list'] });
  });
  if (list.error) reportError(list.error);
  return (
    <Flex vertical gap={16} style={{ width: '100%' }}>
      <PageHeader
        title={t('nav.releases')}
        testId="releases-header"
        extra={
          can('releases.create') && (
            <WriteButton
              type="primary"
              icon={<PlusOutlined />}
              data-testid="new-release"
              onClick={() => void navigate('/releases/new')}
            >
              {t('releases.new')}
            </WriteButton>
          )
        }
      />
      <div role="region" aria-label={t('nav.releases')} tabIndex={0} style={{ overflowX: 'auto' }}>
        <Table<ReleaseListItem>
          rowKey="id"
          data-testid="releases-table"
          loading={list.isPending}
          dataSource={list.data?.items ?? []}
          pagination={false}
          locale={{ emptyText: <EmptyText>{t('releases.empty')}</EmptyText> }}
          onRow={(row) => ({
            onClick: () => void navigate(`/releases/${row.id}`),
            style: { cursor: 'pointer' },
            'data-testid': `release-row-${row.display_id}`,
          })}
          columns={[
            {
              key: 'id',
              title: t('releases.col.id'),
              render: (_, row) => <bdi>{row.display_id}</bdi>,
            },
            {
              key: 'subject',
              title: t('work_item.field.subject'),
              render: (_, row) => (
                <Flex gap={8} align="center" wrap>
                  <bdi>{row.subject}</bdi>
                  {row.stage_path === EMERGENCY_PATH && (
                    <ToneTag
                      tone="error"
                      icon={<ThunderboltOutlined />}
                      testId={`release-emergency-${row.display_id}`}
                    >
                      {t('releases.emergency')}
                    </ToneTag>
                  )}
                </Flex>
              ),
            },
            {
              key: 'stage',
              title: t('work_item.field.stage'),
              render: (_, row) => stageName(t, row.stage),
            },
            {
              key: 'status',
              title: t('work_item.field.status'),
              render: (_, row) => statusName(t, row.status),
            },
            {
              key: 'updated',
              title: t('releases.col.updated'),
              render: (_, row) => format(row.updated_at),
            },
          ]}
        />
      </div>
    </Flex>
  );
}
