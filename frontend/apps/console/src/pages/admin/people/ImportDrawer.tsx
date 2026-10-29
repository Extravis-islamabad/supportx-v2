import { InboxOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Drawer,
  Flex,
  List,
  Progress,
  Radio,
  Space,
  Table,
  Typography,
  Upload,
} from 'antd';
import { useState } from 'react';

import {
  queryKeys,
  usePeopleImports,
  useStartPeopleImport,
  type PeopleImport,
} from '@supportx/api-client';
import { refreshList, useListChannel } from '@supportx/realtime';
import {
  FormProblem,
  ToneTag,
  useAppearance,
  useFormProblem,
  useLabel,
  type Tone,
} from '@supportx/ui';

import { personFieldKey } from './fields';

const MAX_BYTES = 5 * 1024 * 1024;
// File format names as values, so the labels isolate them in right-to-left sentences ("UTF-8"
// would read "8-UTF"); labels never carry direction marks (packages/labels README).
const FORMAT_WORDS = { csv: 'CSV (UTF-8)', xlsx: '.xlsx', utf8: 'UTF-8' };
const STATUS_TONE: Record<PeopleImport['status'], Tone> = {
  queued: 'default',
  running: 'info',
  done: 'success',
  failed: 'error',
};

/**
 * Import people from a CSV file or an Excel workbook (WP-021, REQ-ADM-003). The file is read in
 * the background; progress and refused rows update live on this screen.
 */
export function ImportDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useLabel();
  const { message } = App.useApp();
  const imports = usePeopleImports(open);
  const start = useStartPeopleImport();
  const [matchOn, setMatchOn] = useState<'email' | 'employee_id'>('email');
  const [problem, setProblem] = useState<string>();
  // The server's refusal (a bad file, a limit) is shown here, once (QA WP-029 BUG-02).
  const refused = useFormProblem();
  const queryClient = useQueryClient();
  useListChannel(open ? 'people_imports' : null, () => {
    refreshList(queryClient, queryKeys.people.imports);
  });

  const upload = (file: File) => {
    setProblem(undefined);
    refused.clear();
    if (file.size > MAX_BYTES) {
      setProblem(t('errors.people_import_file_too_large'));
      return;
    }
    start.mutate(
      { file, matchOn },
      {
        onSuccess: () => {
          void message.success(t('people.import.queued', { name: file.name }));
        },
        onError: (error) => {
          refused.show(error);
        },
      },
    );
  };

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={640}
      title={t('people.import.title')}
      destroyOnHidden
      data-testid="people-import-drawer"
    >
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Typography.Paragraph>{t('people.import.explain')}</Typography.Paragraph>
        <Typography.Paragraph type="secondary">{t('people.import.columns')}</Typography.Paragraph>
        <Flex gap={12} align="center" wrap>
          <Typography.Text id="import-match">{t('people.import.match_on')}</Typography.Text>
          <Radio.Group
            aria-labelledby="import-match"
            value={matchOn}
            onChange={(event) => {
              setMatchOn(event.target.value as 'email' | 'employee_id');
            }}
            options={(['email', 'employee_id'] as const).map((value) => ({
              value,
              label: t(`people_import_match.${value}`),
            }))}
          />
        </Flex>
        <Upload.Dragger
          accept=".csv,.txt,.xlsx"
          multiple={false}
          showUploadList={false}
          disabled={start.isPending}
          beforeUpload={(file) => {
            upload(file);
            return false; // sent by the API client, not by the Upload component
          }}
          data-testid="people-import-file"
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">{t('people.import.drop')}</p>
          <p className="ant-upload-hint">{t('people.import.limits', FORMAT_WORDS)}</p>
        </Upload.Dragger>
        {problem !== undefined && (
          <Alert type="error" showIcon message={problem} data-testid="people-import-problem" />
        )}
        <FormProblem problem={refused} />
        <Typography.Title level={4}>{t('people.import.recent')}</Typography.Title>
        <List
          dataSource={imports.data ?? []}
          loading={imports.isPending}
          locale={{ emptyText: t('people.import.none') }}
          renderItem={(job) => <ImportItem job={job} />}
        />
      </Space>
    </Drawer>
  );
}

function ImportItem({ job }: { job: PeopleImport }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const [showProblems, setShowProblems] = useState(false);
  const percent = job.total === 0 ? 0 : Math.round((job.processed / job.total) * 100);
  const when = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });
  return (
    <List.Item data-testid={`people-import-${job.id}`}>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Flex justify="space-between" gap={8} wrap>
          <Typography.Text strong>
            <bdi>{job.file_name}</bdi>
          </Typography.Text>
          <ToneTag tone={STATUS_TONE[job.status]} testId="people-import-status">
            {t(`people_import_status.${job.status}`)}
          </ToneTag>
        </Flex>
        <Typography.Text type="secondary">{when.format(new Date(job.created_at))}</Typography.Text>
        {job.status === 'failed' && job.failure !== null && (
          <Alert
            type="error"
            showIcon
            message={t(`people_import_failure.${job.failure}`, {
              ...FORMAT_WORDS,
              detail: job.problems[0]?.detail ?? '',
            })}
          />
        )}
        {job.status !== 'failed' && (
          <Progress
            percent={percent}
            status={job.status === 'running' ? 'active' : 'normal'}
            aria-label={t('people.import.progress')}
          />
        )}
        <Typography.Text data-testid="people-import-counts">
          {t('people.import.counts', {
            processed: job.processed,
            total: job.total,
            created: job.created_count,
            updated: job.updated_count,
            failed: job.failed_count,
          })}
        </Typography.Text>
        {job.failed_count > 0 && job.status !== 'failed' && (
          <>
            <Button
              type="link"
              style={{ paddingInline: 0 }}
              onClick={() => {
                setShowProblems((shown) => !shown);
              }}
            >
              {showProblems ? t('people.import.hide_problems') : t('people.import.show_problems')}
            </Button>
            {showProblems && (
              <Table
                size="small"
                rowKey={(row) => `${String(row.row)}-${row.field ?? ''}`}
                pagination={{ pageSize: 10, hideOnSinglePage: true }}
                dataSource={job.problems}
                columns={[
                  { key: 'row', title: t('people.import.row'), render: (_, row) => row.row },
                  {
                    key: 'field',
                    title: t('people.import.column'),
                    render: (_, row) =>
                      row.field === null || row.field === 'row' ? '' : t(personFieldKey(row.field)),
                  },
                  {
                    key: 'problem',
                    title: t('people.import.problem'),
                    render: (_, row) =>
                      t(
                        row.field === 'row' || row.code.endsWith('_limit_reached')
                          ? `errors.${row.code}`
                          : `errors.field.${row.code}`,
                      ),
                  },
                ]}
              />
            )}
          </>
        )}
      </Space>
    </List.Item>
  );
}
