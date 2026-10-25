import { Alert, Button, Card, Descriptions, Flex, Space, Table, Typography } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  queryKeys,
  useAuditRuns,
  useAuditStatus,
  useStartAuditRun,
  type AuditRun,
} from '@supportx/api-client';
import { refreshList, useListChannel } from '@supportx/realtime';
import { DateTimeRangeField, useAccess, useDateTime, useLabel } from '@supportx/ui';

import { ProblemAlert } from './ProblemAlert';
import { StateTag } from './StateTag';

const RUN_COLOURS: Record<string, string> = {
  passed: 'success',
  failed: 'error',
  running: 'processing',
  error: 'warning',
};

/**
 * The integrity panel (REQ-AUD-010): how much is sealed, what waits, whether anchoring is on,
 * the last daily, weekly and on-demand verifications, and "verify a range now" for holders of
 * `audit.verify`. A failed run names the first broken entry and its time. Live.
 */
export function IntegrityTab() {
  const t = useLabel();
  const dates = useDateTime();
  const { can } = useAccess();
  const status = useAuditStatus();
  const runs = useAuditRuns();
  const start = useStartAuditRun();
  const [range, setRange] = useState<[string | null, string | null]>([null, null]);
  const queryClient = useQueryClient();
  useListChannel('audit', () => {
    refreshList(queryClient, queryKeys.audit.status);
    refreshList(queryClient, queryKeys.audit.runs);
  });
  const s = status.data;
  const runStatus = (run: AuditRun | null | undefined) =>
    run === null || run === undefined ? (
      t('audit.ui.never')
    ) : (
      <>
        <StateTag tone={RUN_COLOURS[run.status]}>{t(`audit.run_status.${run.status}`)}</StateTag>
        {dates.formatExact(run.finished_at ?? run.started_at)}
      </>
    );
  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      {s !== undefined && !s.anchoring_configured && (
        <Alert
          type="warning"
          showIcon
          message={t('audit.ui.anchoring_off')}
          data-testid="audit-anchoring-off"
        />
      )}
      <Card title={t('audit.ui.integrity')} loading={status.isPending}>
        {s !== undefined && (
          <Descriptions column={{ xs: 1, md: 2 }} size="small">
            <Descriptions.Item label={t('audit.ui.sealed_entries')}>
              {s.sealed_entries}
            </Descriptions.Item>
            <Descriptions.Item label={t('audit.pending_seal')}>
              {s.pending_seal}
              {s.pending_overdue > 0 && (
                <StateTag tone="error" style={{ marginInlineStart: 8 }}>
                  {t('audit.ui.overdue', { count: s.pending_overdue })}
                </StateTag>
              )}
            </Descriptions.Item>
            <Descriptions.Item label={t('audit.ui.last_anchor')}>
              {s.last_anchor_at === null
                ? t('audit.ui.never')
                : t('audit.ui.anchor_at', {
                    time: dates.formatExact(s.last_anchor_at),
                    seq: s.last_anchor_seq ?? 0,
                  })}
            </Descriptions.Item>
            <Descriptions.Item label={t('audit.ui.last_daily')}>
              {runStatus(s.last_daily)}
            </Descriptions.Item>
            <Descriptions.Item label={t('audit.ui.last_weekly')}>
              {runStatus(s.last_weekly)}
            </Descriptions.Item>
            <Descriptions.Item label={t('audit.ui.last_on_demand')}>
              {runStatus(s.last_on_demand)}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Card>
      {can('audit.verify') && (
        <Card title={t('audit.ui.verify_now')}>
          <Flex gap={12} wrap align="center">
            <DateTimeRangeField
              value={range}
              onChange={(value) => {
                setRange(value);
              }}
              testId="audit-verify-range"
            />
            <Button
              type="primary"
              loading={start.isPending}
              data-testid="audit-verify-start"
              onClick={() => {
                start.mutate({ range_from: range[0], range_to: range[1] });
              }}
            >
              {t('audit.ui.verify_start')}
            </Button>
            <Typography.Text type="secondary">{t('audit.ui.verify_help')}</Typography.Text>
          </Flex>
          {start.error !== null && <ProblemAlert error={start.error} />}
        </Card>
      )}
      <Table<AuditRun>
        rowKey="id"
        size="small"
        data-testid="audit-runs"
        loading={runs.isPending}
        dataSource={runs.data ?? []}
        pagination={false}
        columns={[
          {
            key: 'kind',
            title: t('audit.ui.run.kind'),
            render: (_, run) => t(`audit.run_kind.${run.kind}`),
          },
          { key: 'status', title: t('audit.ui.run.status'), render: (_, run) => runStatus(run) },
          {
            key: 'range',
            title: t('audit.ui.run.range'),
            render: (_, run) =>
              run.range_from === null && run.range_to === null
                ? t('audit.ui.run.everything')
                : `${dates.format(run.range_from)} – ${dates.format(run.range_to)}`,
          },
          {
            key: 'checked',
            title: t('audit.ui.run.checked'),
            render: (_, run) => run.entries_checked,
          },
          {
            key: 'problem',
            title: t('audit.ui.run.problem'),
            render: (_, run) =>
              run.problem === null ? null : (
                <Space direction="vertical" size={0}>
                  <Typography.Text type="danger">
                    {t(`audit.problem.${run.problem}`)}
                  </Typography.Text>
                  {run.first_broken_seq !== null && (
                    <Typography.Text type="secondary">
                      {t('audit.ui.first_broken', { seq: run.first_broken_seq })}
                    </Typography.Text>
                  )}
                </Space>
              ),
          },
        ]}
      />
    </Space>
  );
}
