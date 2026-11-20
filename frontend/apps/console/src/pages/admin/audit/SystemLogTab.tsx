import { useQueryClient } from '@tanstack/react-query';
import { Button, Flex, Select, Table, Tag, Typography } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import { useMemo, useState } from 'react';
import { Link } from 'react-router';

import {
  downloadSystemLog,
  queryKeys,
  useSystemLog,
  type SystemLogEntry,
  type SystemLogFilters,
  type SystemLogSeverity,
} from '@supportx/api-client';
import { refreshList, useListChannel } from '@supportx/realtime';
import {
  DateTimeRangeField,
  EmptyText,
  useAccess,
  useAppearance,
  useDateTime,
  useLabel,
} from '@supportx/ui';

import { ProblemAlert } from './ProblemAlert';

const SEVERITIES: SystemLogSeverity[] = ['error', 'warning', 'info'];
const SEVERITY_COLOUR: Record<SystemLogSeverity, string> = {
  error: 'error',
  warning: 'warning',
  info: 'default',
};
const MODULES = [
  'audit',
  'files',
  'integrations',
  'identity_access',
  'licensing',
  'automation',
  'work_items',
  'assets',
  'organization',
] as const;
// Where an entry's object opens (the screens that own those records).
const OBJECT_PATH: Record<string, (id: string) => string> = {
  mailbox: () => '/admin/mail',
  connection: () => '/admin/integrations',
  automation_run: () => '/admin/automation',
  audit_archive: () => '/admin/audit?tab=archives',
};

type Language = 'en' | 'ar' | 'ur';

/**
 * Audit › System log (WP-057 S5b, REQ-AUD-016): what the platform did on its own, and what
 * failed (mailbox checks, syncs, imports, retention). Each entry is a code in words with its
 * object linked; nothing here changes or removes an entry. Live: a new entry refetches the open
 * list. Export gives the filtered rows as CSV in the reader's language (audit.export, audited).
 */
export function SystemLogTab() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { can } = useAccess();
  const dates = useDateTime();
  const queryClient = useQueryClient();
  const [severity, setSeverity] = useState<SystemLogSeverity[]>([]);
  const [modules, setModules] = useState<string[]>([]);
  const [range, setRange] = useState<[string | null, string | null]>([null, null]);
  const [exportError, setExportError] = useState<unknown>(null);
  const [exporting, setExporting] = useState(false);
  const filters = useMemo<SystemLogFilters>(
    () => ({
      ...(severity.length > 0 ? { severity } : {}),
      ...(modules.length > 0 ? { module: modules } : {}),
      ...(range[0] !== null ? { since: range[0] } : {}),
      ...(range[1] !== null ? { until: range[1] } : {}),
    }),
    [severity, modules, range],
  );
  const log = useSystemLog(filters);
  useListChannel('system_log', () => {
    refreshList(queryClient, queryKeys.audit.systemLogAll);
  });
  const rows = useMemo(() => log.data?.pages.flatMap((page) => page.items) ?? [], [log.data]);

  const exportCsv = async () => {
    setExportError(null);
    setExporting(true);
    try {
      const language: Language = locale === 'ar' || locale === 'ur' ? locale : 'en';
      const blob = await downloadSystemLog(filters, language);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'supportx-system-log.csv';
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setExportError(error);
    } finally {
      setExporting(false);
    }
  };

  return (
    <Flex vertical gap={16} data-testid="system-log">
      <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
        {t('audit.system_log.intro')}
      </Typography.Paragraph>
      <Flex gap={8} wrap align="center">
        <Select<SystemLogSeverity[]>
          mode="multiple"
          allowClear
          aria-label={t('audit.system_log.column.severity')}
          placeholder={t('audit.system_log.any_severity')}
          style={{ minWidth: 200 }}
          value={severity}
          options={SEVERITIES.map((s) => ({ value: s, label: t(`system_log_severity.${s}`) }))}
          onChange={setSeverity}
          data-testid="system-log-severity"
        />
        <Select<string[]>
          mode="multiple"
          allowClear
          aria-label={t('audit.system_log.column.module')}
          placeholder={t('audit.system_log.any_module')}
          style={{ minWidth: 220 }}
          value={modules}
          options={MODULES.map((m) => ({ value: m, label: t(`system_log_module.${m}`) }))}
          onChange={setModules}
          data-testid="system-log-module"
        />
        <DateTimeRangeField value={range} onChange={setRange} testId="system-log-range" />
        {can('audit.export') && (
          <Button
            icon={<DownloadOutlined />}
            loading={exporting}
            onClick={() => void exportCsv()}
            data-testid="system-log-export"
          >
            {t('audit.system_log.export')}
          </Button>
        )}
      </Flex>
      {exportError !== null && <ProblemAlert error={exportError} />}
      {log.isError && <ProblemAlert error={log.error} />}
      <Table<SystemLogEntry>
        rowKey="id"
        size="small"
        loading={log.isLoading}
        dataSource={rows}
        pagination={false}
        scroll={{ x: true }}
        locale={{ emptyText: <EmptyText>{t('audit.system_log.none')}</EmptyText> }}
        data-testid="system-log-list"
        columns={[
          {
            key: 'when',
            title: t('audit.system_log.column.occurred_at'),
            render: (_, row) => dates.format(row.occurred_at),
          },
          {
            key: 'severity',
            title: t('audit.system_log.column.severity'),
            render: (_, row) => (
              <Tag color={SEVERITY_COLOUR[row.severity]}>
                {t(`system_log_severity.${row.severity}`)}
              </Tag>
            ),
          },
          {
            key: 'module',
            title: t('audit.system_log.column.module'),
            render: (_, row) => t(`system_log_module.${row.module}`),
          },
          {
            key: 'message',
            title: t('audit.system_log.column.message'),
            render: (_, row) => t(`system_log_code.${row.code}`, row.params),
          },
          {
            key: 'about',
            title: t('audit.system_log.column.object_type'),
            render: (_, row) => {
              if (row.object_type === null || row.object_id === null) return null;
              const name = t(`system_log_object.${row.object_type}`);
              const path = OBJECT_PATH[row.object_type];
              return path === undefined ? name : <Link to={path(row.object_id)}>{name}</Link>;
            },
          },
        ]}
      />
      {log.hasNextPage && (
        <Button
          onClick={() => void log.fetchNextPage()}
          loading={log.isFetchingNextPage}
          data-testid="system-log-more"
        >
          {t('audit.ui.load_more')}
        </Button>
      )}
    </Flex>
  );
}
