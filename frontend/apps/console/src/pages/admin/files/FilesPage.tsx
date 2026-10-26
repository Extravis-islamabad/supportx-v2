import {
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
import { useEffect } from 'react';

import {
  useFileRules,
  useFileStatus,
  useFileUsage,
  useUpdateFileRules,
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

import { FilesBanner } from './FilesBanner';

/**
 * Admin › Files (WP-022, D-081): the tenant's file rules (largest file up to 100 MB, files per
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
  const [form] = Form.useForm<FileRulesInput>();
  useEffect(() => {
    if (rules.data !== undefined) {
      form.setFieldsValue({
        max_file_mb: rules.data.max_file_mb,
        max_batch: rules.data.max_batch,
        blocked_extensions: rules.data.blocked_extensions,
      });
    }
  }, [rules.data, form]);

  const used = usage.data?.bytes_used ?? 0;
  const limit = usage.data?.limit_bytes ?? null;
  const scanning = status.data;
  return (
    <Flex vertical gap={16} data-testid="admin-files">
      <FilesBanner showLink={false} />
      <Card title={t('files.admin.rules')}>
        <Form<FileRulesInput>
          form={form}
          layout="vertical"
          style={{ maxWidth: 640 }}
          onFinish={(values) => {
            save.mutate(
              { body: values, version: rules.data?.version ?? 0 },
              {
                onSuccess: () => void message.success(t('files.admin.saved')),
                onError: reportError,
              },
            );
          }}
        >
          <Form.Item
            name="max_file_mb"
            label={t('files.admin.max_file_mb')}
            rules={[{ required: true, type: 'number', min: 1, max: 100 }]}
          >
            <InputNumber min={1} max={100} data-testid="files-max-mb" />
          </Form.Item>
          <Form.Item
            name="max_batch"
            label={t('files.admin.max_batch')}
            rules={[{ required: true, type: 'number', min: 1, max: 50 }]}
          >
            <InputNumber min={1} max={50} data-testid="files-max-batch" />
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
