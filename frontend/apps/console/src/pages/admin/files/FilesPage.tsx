import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Flex,
  Form,
  InputNumber,
  Progress,
  Select,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useFileRules,
  useFileStatus,
  useFileUsage,
  useUpdateFileRules,
  type FileRules,
  type FileRulesInput,
} from '@supportx/api-client';
import {
  formatSize,
  reportError,
  useAppearance,
  useDateTime,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { numberProblem } from '../../../numbers';
import { FilesBanner } from './FilesBanner';

/**
 * Admin › Files (WP-022, D-082): the tenant's file rules (largest file up to 100 MB, files per
 * upload, blocked types), storage use against the plan's limit, and the malware-scanning status.
 * Changing the rules is audited with the old and new values.
 */
export function FilesPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const dates = useDateTime();
  const { message } = App.useApp();
  const rules = useFileRules();
  const usage = useFileUsage();
  const status = useFileStatus();
  const save = useUpdateFileRules();
  // The saved rules the form was filled from: their version goes with the save, so rules
  // saved elsewhere meanwhile are never overwritten (QA WP-026 BUG-01). Live changes refill an
  // untouched form; while the admin is editing they are announced instead.
  const [base, setBase] = useState<FileRules | null>(null);
  const [dirty, setDirty] = useState(false);
  const latest = rules.data;
  if (latest !== undefined && latest.version !== base?.version && (base === null || !dirty)) {
    setBase(latest);
  }
  const stale = base !== null && latest !== undefined && latest.version !== base.version;
  // Out-of-range numbers are refused at the field, never clamped (QA WP-026 BUG-03).
  const limits = (min: number, max: number) => [
    { required: true, message: t('errors.field.required') },
    {
      validator: (_: unknown, value: number | null) => {
        const problem = numberProblem(t, value, { min, max, whole: true });
        return problem === null ? Promise.resolve() : Promise.reject(new Error(problem));
      },
    },
  ];

  const used = usage.data?.bytes_used ?? 0;
  const limit = usage.data?.limit_bytes ?? null;
  const scanning = status.data;
  return (
    <Flex vertical gap={16} data-testid="admin-files">
      <FilesBanner showLink={false} />
      <Card title={t('files.admin.rules')}>
        {stale && (
          <Alert
            type="warning"
            showIcon
            role="status"
            style={{ marginBottom: 12 }}
            message={t('settings.stale')}
            action={
              <Button
                size="small"
                onClick={() => {
                  setBase(latest);
                  setDirty(false);
                }}
                data-testid="files-rules-stale-reload"
              >
                {t('live.reload')}
              </Button>
            }
            data-testid="files-rules-stale"
          />
        )}
        <Form<FileRulesInput>
          // A new saved version is a new form, filled from it (no effect needed).
          key={base?.version ?? 'loading'}
          initialValues={
            base === null
              ? undefined
              : {
                  max_file_mb: base.max_file_mb,
                  max_batch: base.max_batch,
                  blocked_extensions: base.blocked_extensions,
                }
          }
          layout="vertical"
          style={{ maxWidth: 640 }}
          onValuesChange={() => {
            setDirty(true);
          }}
          onFinish={(values) => {
            save.mutate(
              { body: values, version: base?.version ?? latest?.version ?? 0 },
              {
                onSuccess: (saved) => {
                  setBase(saved);
                  setDirty(false);
                  void message.success(t('files.admin.saved'));
                },
                onError: (error) => {
                  if (error instanceof ApiError && error.code === 'version_conflict') {
                    void message.warning(t('settings.changed_elsewhere'));
                    return;
                  }
                  reportError(error);
                },
              },
            );
          }}
        >
          <Form.Item name="max_file_mb" label={t('files.admin.max_file_mb')} rules={limits(1, 100)}>
            <InputNumber data-testid="files-max-mb" />
          </Form.Item>
          <Form.Item name="max_batch" label={t('files.admin.max_batch')} rules={limits(1, 50)}>
            <InputNumber data-testid="files-max-batch" />
          </Form.Item>
          <Form.Item
            name="blocked_extensions"
            label={t('files.admin.blocked')}
            extra={t('files.admin.blocked_hint')}
          >
            <Select
              mode="tags"
              tokenSeparators={[',', ' ']}
              open={false}
              suffixIcon={null}
              aria-label={t('files.admin.blocked')}
              data-testid="files-blocked"
            />
          </Form.Item>
          <WriteButton
            type="primary"
            htmlType="submit"
            loading={save.isPending}
            data-testid="files-save"
          >
            {t('files.admin.save')}
          </WriteButton>
        </Form>
      </Card>
      <Card title={t('files.admin.usage')} data-testid="files-usage">
        {usage.data !== undefined && (
          <Flex vertical gap={8} style={{ maxWidth: 480 }}>
            <Typography.Text>
              {limit === null
                ? t('files.admin.used_unlimited', { used: formatSize(used, locale) })
                : t('files.admin.used_of', {
                    used: formatSize(used, locale),
                    limit: formatSize(limit, locale),
                  })}
            </Typography.Text>
            {limit !== null && (
              <Progress
                percent={Math.min(100, Math.round((used / Math.max(limit, 1)) * 100))}
                aria-label={t('files.admin.usage')}
              />
            )}
            <Typography.Text type="secondary">
              {t('files.admin.files_count', { count: usage.data.files })}
            </Typography.Text>
          </Flex>
        )}
      </Card>
      <Card title={t('files.admin.scanning')} data-testid="files-scanning">
        {scanning !== undefined && (
          <Descriptions column={1} size="small">
            <Descriptions.Item label={t('files.admin.scanning')}>
              {scanning.warnings.length === 0
                ? t('files.admin.scanning_ok')
                : scanning.warnings.map((w) => t(`file_warning.${w}`)).join(' ')}
            </Descriptions.Item>
            {scanning.signature_date !== null && (
              <Descriptions.Item label={t('files.admin.signatures')}>
                {dates.format(scanning.signature_date)}
              </Descriptions.Item>
            )}
            <Descriptions.Item label={t('file_state.scanning')}>
              {t('files.admin.waiting', { count: scanning.waiting })}
            </Descriptions.Item>
            <Descriptions.Item label={t('file_state.scan_failed')}>
              {t('files.admin.failed', { count: scanning.failed })}
            </Descriptions.Item>
            <Descriptions.Item label={t('file_state.not_scanned')}>
              {t('files.admin.not_scanned', { count: scanning.not_scanned })}
            </Descriptions.Item>
          </Descriptions>
        )}
        <Button
          style={{ marginTop: 12 }}
          onClick={() => void status.refetch()}
          data-testid="files-status-refresh"
        >
          {t('files.admin.check_now')}
        </Button>
      </Card>
    </Flex>
  );
}
