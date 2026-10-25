import { Alert, Button, Drawer, Flex, Space, Table, Tag, Typography } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  queryKeys,
  useAuditArchives,
  useRestoreAuditArchive,
  useRestoredAuditEntries,
  type AuditArchive,
  type AuditEntry,
} from '@supportx/api-client';
import { refreshList, useListChannel } from '@supportx/realtime';
import { useAccess, useDateTime, useLabel } from '@supportx/ui';

import { ProblemAlert } from './ProblemAlert';
import { actorLabel, OUTCOME_COLOURS } from './present';

const RESTORE_COLOURS: Record<string, string> = {
  running: 'processing',
  ready: 'success',
  failed: 'error',
};

/**
 * Archives (retention, D-076 item 10): months past the retention period, written to object
 * storage and verified. Failed attempts are listed with their reason, never hidden. An auditor
 * can restore a month for an investigation: it is verified again and readable for 7 days.
 * Live through the audit channel.
 */
export function ArchivesTab() {
  const t = useLabel();
  const dates = useDateTime();
  const { can } = useAccess();
  const archives = useAuditArchives();
  const restore = useRestoreAuditArchive();
  const [open, setOpen] = useState<AuditArchive | null>(null);
  const queryClient = useQueryClient();
  useListChannel('audit', () => {
    refreshList(queryClient, queryKeys.audit.archives);
  });

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        {t('audit.ui.archive.help')}
      </Typography.Paragraph>
      {restore.error !== null && <ProblemAlert error={restore.error} />}
      <Table<AuditArchive>
        rowKey="id"
        size="small"
        data-testid="audit-archives"
        loading={archives.isPending}
        dataSource={archives.data ?? []}
        pagination={{ pageSize: 24, hideOnSinglePage: true }}
        locale={{ emptyText: t('audit.ui.archive.none') }}
        columns={[
          {
            key: 'month',
            title: t('audit.ui.archive.month'),
            render: (_, row) => dates.formatMonth(row.range_from),
          },
          {
            key: 'status',
            title: t('audit.ui.export.status'),
            render: (_, row) => (
              <Space direction="vertical" size={0}>
                <Tag color={row.status === 'ready' ? 'success' : 'error'}>
                  {t(`audit.archive_status.${row.status}`)}
                </Tag>
                {row.problem !== null && (
                  <Typography.Text type="danger">{t(`errors.${row.problem}`)}</Typography.Text>
                )}
              </Space>
            ),
          },
          {
            key: 'entries',
            title: t('audit.ui.export.entries'),
            render: (_, row) => (row.status === 'ready' ? row.entries : null),
          },
          {
            key: 'positions',
            title: t('audit.ui.col.seal'),
            render: (_, row) =>
              row.first_seq === null || row.last_seq === null
                ? null
                : t('audit.ui.archive.positions', { first: row.first_seq, last: row.last_seq }),
          },
          {
            key: 'restore',
            title: t('audit.ui.archive.restore'),
            render: (_, row) => {
              if (row.status !== 'ready') return null;
              return (
                <Space direction="vertical" size={0}>
                  {row.restore_status !== null && (
                    <Tag color={RESTORE_COLOURS[row.restore_status]}>
                      {t(`audit.restore_status.${row.restore_status}`)}
                    </Tag>
                  )}
                  {row.restore_problem !== null && (
                    <Typography.Text type="danger">
                      {t(`errors.${row.restore_problem}`)}
                    </Typography.Text>
                  )}
                  {row.restore_status === 'ready' ? (
                    <>
                      <Button
                        size="small"
                        data-testid={`audit-archive-open-${row.id}`}
                        onClick={() => {
                          setOpen(row);
                        }}
                      >
                        {t('audit.ui.archive.open')}
                      </Button>
                      <Typography.Text type="secondary">
                        {t('audit.ui.archive.until', { time: dates.format(row.restored_until) })}
                      </Typography.Text>
                    </>
                  ) : (
                    can('audit.export') &&
                    row.restore_status !== 'running' && (
                      <Button
                        size="small"
                        loading={restore.isPending && restore.variables === row.id}
                        data-testid={`audit-archive-restore-${row.id}`}
                        onClick={() => {
                          restore.mutate(row.id);
                        }}
                      >
                        {t('audit.ui.archive.restore')}
                      </Button>
                    )
                  )}
                </Space>
              );
            },
          },
        ]}
      />
      <RestoredDrawer
        archive={open}
        onClose={() => {
          setOpen(null);
        }}
      />
    </Space>
  );
}

function RestoredDrawer({
  archive,
  onClose,
}: {
  archive: AuditArchive | null;
  onClose: () => void;
}) {
  const t = useLabel();
  const dates = useDateTime();
  const entries = useRestoredAuditEntries(archive?.id);
  const rows: AuditEntry[] = entries.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <Drawer
      open={archive !== null}
      onClose={onClose}
      width={880}
      title={archive === null ? null : dates.formatMonth(archive.range_from)}
      data-testid="audit-restored-drawer"
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Alert type="info" showIcon message={t('audit.ui.archive.restored_help')} />
        {entries.error !== null && <ProblemAlert error={entries.error} />}
        <Table<AuditEntry>
          rowKey="id"
          size="small"
          data-testid="audit-restored-table"
          loading={entries.isPending}
          dataSource={rows}
          pagination={false}
          columns={[
            {
              key: 'time',
              title: t('audit.ui.col.time'),
              render: (_, entry) => dates.formatExact(entry.occurred_at),
            },
            { key: 'actor', title: t('audit.ui.col.actor'), render: (_, e) => actorLabel(t, e) },
            {
              key: 'action',
              title: t('audit.ui.col.action'),
              render: (_, entry) => t(`audit.action.${entry.action}`),
            },
            {
              key: 'outcome',
              title: t('audit.ui.col.outcome'),
              render: (_, entry) => (
                <Tag color={OUTCOME_COLOURS[entry.outcome]}>
                  {t(`audit_outcome.${entry.outcome}`)}
                </Tag>
              ),
            },
            {
              key: 'seal',
              title: t('audit.ui.col.seal'),
              render: (_, entry) =>
                entry.seq === null ? null : t('audit.ui.sealed_at_position', { seq: entry.seq }),
            },
          ]}
        />
        {entries.hasNextPage && (
          <Flex justify="center">
            <Button
              loading={entries.isFetchingNextPage}
              onClick={() => {
                void entries.fetchNextPage();
              }}
            >
              {t('audit.ui.load_more')}
            </Button>
          </Flex>
        )}
      </Space>
    </Drawer>
  );
}
