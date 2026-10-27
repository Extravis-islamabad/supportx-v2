import { DownloadOutlined, SettingOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  App as AntApp,
  Button,
  Drawer,
  Form,
  InputNumber,
  List,
  Modal,
  Radio,
  Select,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  exportFileUrl,
  queryKeys,
  useMyExports,
  useReportSettings,
  useRequestExport,
  useUpdateReportSettings,
  type ReportDefinition,
  type ReportExport,
  type ReportExportInput,
} from '@supportx/api-client';
import { useLabels } from '@supportx/labels';
import { refreshList, usePersonalChannel } from '@supportx/realtime';
import {
  describeError,
  ToneTag,
  useAccess,
  useAppearance,
  useDateTime,
  WriteButton,
  type Tone,
} from '@supportx/ui';

type Format = ReportExportInput['format'];
type Content = NonNullable<ReportExportInput['content']>;

const FORMATS: Format[] = ['xlsx', 'csv', 'pdf'];
const CONTENTS: Content[] = ['summary', 'records'];
const STATUS_TONE: Record<ReportExport['status'], Tone> = {
  running: 'info',
  ready: 'success',
  failed: 'error',
  expired: 'default',
};

/** "Export" on a report: file type and contents; the file is built in the background. */
export function ExportButton({
  title,
  definition,
  canRun,
}: {
  title: string;
  definition: ReportDefinition;
  canRun: boolean;
}) {
  const t = useLabels();
  const { can } = useAccess();
  const { locale } = useAppearance();
  const { message } = AntApp.useApp();
  const request = useRequestExport();
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState<Format>('xlsx');
  const [content, setContent] = useState<Content>('summary');
  const [key, setKey] = useState(() => crypto.randomUUID());
  const allowed = can('reports.export') && canRun;
  const language = (['en', 'ar', 'ur'] as const).find((l) => l === locale) ?? 'en';

  return (
    <>
      <Tooltip title={allowed ? undefined : t('reports.cannot_export')}>
        <Button
          icon={<DownloadOutlined />}
          disabled={!allowed}
          onClick={() => {
            setOpen(true);
          }}
          data-testid="report-export"
        >
          {t('reports.export')}
        </Button>
      </Tooltip>
      <Modal
        open={open}
        title={t('reports.export_title')}
        okText={t('reports.export')}
        cancelText={t('reports.cancel')}
        okButtonProps={{ loading: request.isPending }}
        onCancel={() => {
          setOpen(false);
        }}
        onOk={() => {
          request.mutate(
            { key, body: { title, definition, format, content, language } },
            {
              onSuccess: () => {
                setOpen(false);
                setKey(crypto.randomUUID());
                void message.info(t('reports.export_started'));
              },
            },
          );
        }}
      >
        <Form layout="vertical">
          <Form.Item label={t('reports.export_format')}>
            <Radio.Group
              value={format}
              onChange={(event) => {
                setFormat(event.target.value as Format);
              }}
              options={FORMATS.map((f) => ({ value: f, label: t(`report_export_format.${f}`) }))}
              data-testid="report-export-format"
            />
          </Form.Item>
          <Form.Item label={t('reports.export_content')}>
            <Radio.Group
              value={content}
              onChange={(event) => {
                setContent(event.target.value as Content);
              }}
              options={CONTENTS.map((c) => ({ value: c, label: t(`report_export_content.${c}`) }))}
              data-testid="report-export-content"
            />
          </Form.Item>
          {request.error && (
            <Typography.Text type="danger" role="alert">
              {describeError(request.error, t).title}
            </Typography.Text>
          )}
        </Form>
      </Modal>
    </>
  );
}

/** "My exports": what was asked for, its state, and the file while it lasts. Live. */
export function MyExportsButton() {
  const t = useLabels();
  const dates = useDateTime();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const exports = useMyExports(open);
  usePersonalChannel((message) => {
    if (message.type === 'reports.export_finished') {
      refreshList(queryClient, queryKeys.reports.exports);
    }
  });

  return (
    <>
      <Button
        onClick={() => {
          setOpen(true);
        }}
        data-testid="report-my-exports"
      >
        {t('reports.my_exports')}
      </Button>
      <Drawer
        open={open}
        title={t('reports.my_exports')}
        onClose={() => {
          setOpen(false);
        }}
        width={480}
        data-testid="report-exports-drawer"
      >
        <List
          loading={exports.isPending}
          dataSource={exports.data ?? []}
          locale={{ emptyText: t('reports.no_exports') }}
          renderItem={(item) => (
            <List.Item
              actions={
                item.status === 'ready'
                  ? [
                      <a
                        key="download"
                        href={exportFileUrl(item.id)}
                        download
                        data-testid={`report-export-download-${item.id}`}
                      >
                        {t('reports.download')}
                      </a>,
                    ]
                  : []
              }
            >
              <List.Item.Meta
                title={
                  <Space wrap>
                    <span>{item.title}</span>
                    <Tag>{t(`report_export_format.${item.format}`)}</Tag>
                    <ToneTag
                      tone={STATUS_TONE[item.status]}
                      testId={`report-export-status-${item.id}`}
                    >
                      {t(`report_export_status.${item.status}`)}
                    </ToneTag>
                  </Space>
                }
                description={
                  <Space direction="vertical" size={0}>
                    <span>{dates.format(item.created_at)}</span>
                    {item.row_count !== null && (
                      <span>{t('reports.export_rows', { count: item.row_count })}</span>
                    )}
                    {item.problem && (
                      <Typography.Text type="danger">
                        {t(`report_export_problem.${item.problem}`)}
                      </Typography.Text>
                    )}
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      </Drawer>
    </>
  );
}

/** Report settings for admins (D-041): week start, time limit, link lifetime, rows per file. */
export function ReportSettingsButton() {
  const t = useLabels();
  const { can } = useAccess();
  const [open, setOpen] = useState(false);
  const settings = useReportSettings(open);
  const update = useUpdateReportSettings();
  if (!can('settings.manage')) return null;
  const data = settings.data;

  return (
    <>
      <Button
        icon={<SettingOutlined />}
        onClick={() => {
          setOpen(true);
        }}
        data-testid="report-settings"
      >
        {t('reports.settings')}
      </Button>
      <Drawer
        open={open}
        title={t('reports.settings')}
        onClose={() => {
          setOpen(false);
        }}
        width={420}
      >
        {data && (
          <Form
            layout="vertical"
            key={data.version}
            initialValues={data}
            onFinish={(values: typeof data) => {
              update.mutate({
                version: data.version,
                changes: {
                  week_start: values.week_start,
                  interactive_timeout_seconds: values.interactive_timeout_seconds,
                  export_link_days: values.export_link_days,
                  max_export_rows: values.max_export_rows,
                },
              });
            }}
          >
            <Form.Item name="week_start" label={t('reports.week_start')}>
              <Select
                options={(['monday', 'sunday'] as const).map((d) => ({
                  value: d,
                  label: t(`report_week_start.${d}`),
                }))}
                data-testid="report-settings-week-start"
              />
            </Form.Item>
            <Form.Item name="interactive_timeout_seconds" label={t('reports.timeout_seconds')}>
              <InputNumber min={5} max={60} />
            </Form.Item>
            <Form.Item name="export_link_days" label={t('reports.link_days')}>
              <InputNumber min={1} max={30} />
            </Form.Item>
            <Form.Item name="max_export_rows" label={t('reports.max_rows')}>
              <InputNumber min={1000} max={1_000_000} step={1000} />
            </Form.Item>
            {update.error && (
              <Typography.Paragraph type="danger" role="alert">
                {describeError(update.error, t).title}
              </Typography.Paragraph>
            )}
            <WriteButton
              type="primary"
              htmlType="submit"
              loading={update.isPending}
              data-testid="report-settings-save"
            >
              {t('reports.save')}
            </WriteButton>
          </Form>
        )}
      </Drawer>
    </>
  );
}
