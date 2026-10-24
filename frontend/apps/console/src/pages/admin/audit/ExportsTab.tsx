import { Button, Card, Flex, Radio, Space, Table, Tag, Typography } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  downloadAuditExport,
  queryKeys,
  useAuditExports,
  useStartAuditExport,
  type AuditExport,
} from '@supportx/api-client';
import { refreshList, useListChannel } from '@supportx/realtime';
import { DateTimeRangeField, useDateTime, useLabel } from '@supportx/ui';

import { ProblemAlert } from './ProblemAlert';

const STATUS_COLOURS: Record<string, string> = {
  running: 'processing',
  ready: 'success',
  failed: 'error',
  expired: 'default',
};

function sizeLabel(bytes: number | null): string {
  if (bytes === null) return '';
  return bytes < 1024 * 1024
    ? `${String(Math.ceil(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Exports for auditors (REQ-AUD-009): a time range and a format, built in the background, then a
 * zip with the entries, a signed manifest and the offline verifier. Failures are shown with their
 * reason (storage unavailable ...), never silently. Live.
 */
export function ExportsTab() {
  const t = useLabel();
  const dates = useDateTime();
  const exportsList = useAuditExports();
  const start = useStartAuditExport();
  const [range, setRange] = useState<[string | null, string | null]>([null, null]);
  const [format, setFormat] = useState<'jsonl' | 'csv'>('jsonl');
  const [downloadError, setDownloadError] = useState<unknown>(null);
  const queryClient = useQueryClient();
  useListChannel('audit', () => {
    refreshList(queryClient, queryKeys.audit.exports);
  });

  const download = async (row: AuditExport) => {
    setDownloadError(null);
    try {
      const blob = await downloadAuditExport(row.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `supportx-audit-${row.id}.zip`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setDownloadError(error);
    }
  };

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Card title={t('audit.ui.export.new')}>
        <Flex gap={12} wrap align="center">
          <DateTimeRangeField
            value={range}
            onChange={(value) => {
              setRange(value);
            }}
            testId="audit-export-range"
          />
          <Radio.Group
            value={format}
            onChange={(event) => {
              setFormat(event.target.value as 'jsonl' | 'csv');
            }}
            options={(['jsonl', 'csv'] as const).map((value) => ({
              value,
              label: t(`audit_export_format.${value}`),
            }))}
          />
          <Button
            type="primary"
            loading={start.isPending}
            data-testid="audit-export-start"
            onClick={() => {
              start.mutate({ format, range_from: range[0], range_to: range[1], filters: {} });
            }}
          >
            {t('audit.ui.export.start')}
          </Button>
        </Flex>
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          {t('audit.ui.export.help')}
        </Typography.Paragraph>
        {start.error !== null && <ProblemAlert error={start.error} />}
        {downloadError !== null && <ProblemAlert error={downloadError} />}
      </Card>
      <Table<AuditExport>
        rowKey="id"
        size="small"
        data-testid="audit-exports"
        loading={exportsList.isPending}
        dataSource={exportsList.data ?? []}
        pagination={false}
        columns={[
          {
            key: 'created',
            title: t('audit.ui.export.created'),
            render: (_, row) => dates.formatExact(row.created_at),
          },
          {
            key: 'status',
            title: t('audit.ui.export.status'),
            render: (_, row) => (
              <Space direction="vertical" size={0}>
                <Tag color={STATUS_COLOURS[row.status]}>
                  {t(`audit.export_status.${row.status}`)}
                </Tag>
                {row.problem !== null && (
                  <Typography.Text type="danger">{t(`errors.${row.problem}`)}</Typography.Text>
                )}
              </Space>
            ),
          },
          {
            key: 'range',
            title: t('audit.ui.run.range'),
            render: (_, row) =>
              row.range_from === null && row.range_to === null
                ? t('audit.ui.run.everything')
                : `${dates.format(row.range_from)} – ${dates.format(row.range_to)}`,
          },
          {
            key: 'entries',
            title: t('audit.ui.export.entries'),
            render: (_, row) => (row.status === 'ready' ? row.entries : null),
          },
          {
            key: 'verified',
            title: t('audit.ui.export.verified'),
            render: (_, row) =>
              row.verification === null ? null : t(`audit.run_status.${row.verification}`),
          },
          {
            key: 'download',
            title: t('audit.ui.export.download'),
            render: (_, row) =>
              row.status === 'ready' ? (
                <Space direction="vertical" size={0}>
                  <Button
                    size="small"
                    data-testid={`audit-export-download-${row.id}`}
                    onClick={() => {
                      void download(row);
                    }}
                  >
                    {t('audit.ui.export.download')} ({sizeLabel(row.size_bytes)})
                  </Button>
                  <Typography.Text type="secondary">
                    {t('audit.ui.export.expires', { time: dates.format(row.expires_at) })}
                  </Typography.Text>
                </Space>
              ) : null,
          },
        ]}
      />
    </Space>
  );
}
