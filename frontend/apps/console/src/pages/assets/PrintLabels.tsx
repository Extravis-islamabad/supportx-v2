import { Alert, Flex, Form, Progress, Segmented, Select, Table, Typography } from 'antd';
import { useState } from 'react';

import {
  labelFileUrl,
  useAssetLabelActions,
  useAssetLabelJobs,
  useAssetLabelPrints,
  type AssetLabelJob,
  type AssetLabelLayout,
  type AssetLabelPrint,
  type AssetLabelSymbology,
} from '@supportx/api-client';
import {
  EditDialog,
  FormProblem,
  loadedEmpty,
  RowActions,
  ToneTag,
  useAppearance,
  useDateTime,
  useFormProblem,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { useLabelsLive } from './live';

// Asset labels (WP-049b s3; REQ-AST-039): pick a layout and a code, the worker makes one PDF
// (up to 500 labels) and the person hears of it live on their own channel. The label history
// shows every print and reprint.

const LAYOUTS: AssetLabelLayout[] = ['laptop', 'cable'];
const CODES: AssetLabelSymbology[] = ['qr', 'code128'];
const TONES = { running: 'info', ready: 'success', failed: 'error' } as const;

/** One job: where it stands, and the file once ready. */
export function LabelJobStatus({ job }: { job: AssetLabelJob }) {
  const t = useLabel();
  return (
    <Flex gap={8} align="center" wrap data-testid={`label-job-${job.id}`}>
      <ToneTag tone={TONES[job.status]}>{t(`asset_label_job_status.${job.status}`)}</ToneTag>
      <Typography.Text>{t('assets.labels.count', { count: job.item_count })}</Typography.Text>
      {job.status === 'running' && (
        <Progress
          percent={Math.round((job.done / Math.max(job.item_count, 1)) * 100)}
          size="small"
          status="active"
          style={{ minWidth: 120 }}
          aria-label={t('assets.labels.preparing')}
        />
      )}
      {job.status === 'ready' && (
        <a href={labelFileUrl(job.id)} download data-testid={`label-job-download-${job.id}`}>
          {t('assets.labels.download')}
        </a>
      )}
      {job.status === 'failed' && job.problem !== null && (
        <Typography.Text type="danger">{t(`errors.${job.problem}`)}</Typography.Text>
      )}
    </Flex>
  );
}

/**
 * "Print labels" for the given assets: layout, code and language, then the job's progress and
 * its file. Only assets the person may see can be printed; the server checks each one.
 */
export function PrintLabelsDialog({
  assetIds,
  open,
  onClose,
}: {
  assetIds: string[];
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { print } = useAssetLabelActions();
  const jobs = useAssetLabelJobs(open);
  const problem = useFormProblem();
  const [layout, setLayout] = useState<AssetLabelLayout>('laptop');
  const [symbology, setSymbology] = useState<AssetLabelSymbology>('qr');
  const [language, setLanguage] = useState<'en' | 'ar' | 'ur'>(
    locale === 'ar' || locale === 'ur' ? locale : 'en',
  );
  const [jobId, setJobId] = useState<string>();
  const [key] = useState(() => crypto.randomUUID());
  useLabelsLive();
  const job = jobs.data?.find((j) => j.id === jobId);
  const submit = () => {
    problem.clear();
    print.mutate(
      {
        key,
        body: { target: 'asset', asset_ids: assetIds, layout, symbology, language, codes: [] },
      },
      {
        onSuccess: (made) => {
          setJobId(made.id);
        },
        onError: problem.show,
      },
    );
  };
  return (
    <EditDialog
      open={open}
      title={t('assets.labels.print_title', { count: assetIds.length })}
      okText={jobId === undefined ? t('assets.labels.print') : t('assets.labels.done')}
      saving={print.isPending}
      onOk={jobId === undefined ? submit : onClose}
      onCancel={onClose}
      testId="labels-dialog"
    >
      <FormProblem problem={problem} />
      {jobId === undefined ? (
        <Form layout="vertical">
          <Form.Item label={t('assets.labels.layout')}>
            <Segmented
              value={layout}
              onChange={(value) => {
                setLayout(value);
              }}
              options={LAYOUTS.map((l) => ({ value: l, label: t(`asset_label_layout.${l}`) }))}
              data-testid="labels-layout"
            />
          </Form.Item>
          <Form.Item label={t('assets.labels.code')}>
            <Segmented
              value={symbology}
              onChange={(value) => {
                setSymbology(value);
              }}
              options={CODES.map((c) => ({ value: c, label: t(`asset_label_symbology.${c}`) }))}
              data-testid="labels-code"
            />
          </Form.Item>
          <Form.Item label={t('assets.labels.language')} htmlFor="labels-language">
            <Select
              id="labels-language"
              value={language}
              onChange={setLanguage}
              options={(['en', 'ar', 'ur'] as const).map((l) => ({
                value: l,
                label: t(`locale.${l}`),
              }))}
              data-testid="labels-language"
            />
          </Form.Item>
          <Typography.Paragraph type="secondary">{t('assets.labels.qr_note')}</Typography.Paragraph>
        </Form>
      ) : job === undefined ? (
        <Typography.Text>{t('assets.labels.preparing')}</Typography.Text>
      ) : (
        <LabelJobStatus job={job} />
      )}
    </EditDialog>
  );
}

/** The label history of one asset (REQ-AST-039 AC3): who printed what, when; reprint. */
export function LabelHistory({ assetId }: { assetId: string }) {
  const t = useLabel();
  const dates = useDateTime();
  const prints = useAssetLabelPrints(assetId);
  const { reprint } = useAssetLabelActions();
  const [error, setError] = useState<string>();
  useLabelsLive();
  const again = (row: AssetLabelPrint) => {
    setError(undefined);
    reprint.mutate(
      { printId: row.id, key: crypto.randomUUID() },
      {
        onError: () => {
          setError(t('errors.asset_labels_failed'));
        },
      },
    );
  };
  return (
    <Flex vertical gap={8}>
      {error !== undefined && <Alert type="error" showIcon message={error} />}
      <Table<AssetLabelPrint>
        size="small"
        rowKey="id"
        pagination={false}
        loading={prints.isPending}
        dataSource={prints.data ?? []}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: loadedEmpty(prints.isPending, t('assets.labels.none')) }}
        data-testid="label-history"
        columns={[
          {
            key: 'when',
            title: t('assets.labels.printed_at'),
            render: (_, row) => dates.format(row.printed_at),
          },
          {
            key: 'who',
            title: t('assets.labels.printed_by'),
            render: (_, row) => <bdi dir="auto">{row.printed_by_name ?? ''}</bdi>,
          },
          {
            key: 'layout',
            title: t('assets.labels.layout'),
            render: (_, row) =>
              `${t(`asset_label_layout.${row.layout}`)} · ${t(`asset_label_symbology.${row.symbology}`)}`,
          },
          {
            key: 'count',
            title: t('assets.labels.labels'),
            render: (_, row) => (
              <Flex gap={4} wrap>
                {t('assets.labels.count', { count: row.item_count })}
                {row.reprint && <ToneTag tone="default">{t('assets.labels.reprint')}</ToneTag>}
              </Flex>
            ),
          },
          {
            key: 'actions',
            title: <span className="sr-only">{t('assets.admin.actions')}</span>,
            render: (_, row) => (
              <RowActions
                rowName={dates.format(row.printed_at)}
                primary={{
                  key: 'reprint',
                  label: t('assets.labels.reprint_action'),
                  onClick: () => {
                    again(row);
                  },
                  testId: `label-reprint-${row.id}`,
                }}
              />
            ),
          },
        ]}
      />
    </Flex>
  );
}

/** The person's recent label jobs, live: what is being prepared and what can be downloaded. */
export function MyLabelJobs() {
  const t = useLabel();
  const jobs = useAssetLabelJobs();
  useLabelsLive();
  const recent = (jobs.data ?? []).slice(0, 3);
  if (recent.length === 0) return null;
  return (
    <Flex vertical gap={4} data-testid="my-label-jobs">
      <Typography.Text strong>{t('assets.labels.recent')}</Typography.Text>
      {recent.map((job) => (
        <LabelJobStatus key={job.id} job={job} />
      ))}
    </Flex>
  );
}

/** The button that opens the dialog (asset page and list selection). */
export function PrintLabelsButton({ assetIds, testId }: { assetIds: string[]; testId?: string }) {
  const t = useLabel();
  const [open, setOpen] = useState(false);
  return (
    <>
      <WriteButton
        onClick={() => {
          setOpen(true);
        }}
        disabled={assetIds.length === 0}
        whyDisabled={t('assets.labels.choose_first')}
        data-testid={testId}
      >
        {t('assets.labels.print_action')}
      </WriteButton>
      {open && (
        <PrintLabelsDialog
          assetIds={assetIds}
          open={open}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </>
  );
}
