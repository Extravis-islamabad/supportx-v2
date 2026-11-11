import { UploadOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Drawer,
  Flex,
  Form,
  Progress,
  Select,
  Steps,
  Table,
  Typography,
} from 'antd';
import { useRef, useState } from 'react';

import {
  ASSET_IMPORT_PROGRESS,
  assetBatchKeys,
  queryKeys,
  useAssetImport,
  useRunAssetImport,
  useStartAssetImport,
  type AssetImport,
  type AssetImportKind,
  type AssetImportMatch,
  type AssetImportMode,
  type AssetImportProblem,
} from '@supportx/api-client';
import { usePersonalChannel } from '@supportx/realtime';
import { useAccess, useLabel, WriteButton } from '@supportx/ui';

import { columnText, failureText, problemsCsv, reasonText, WORDS } from './batch';
import { problemText } from './problemText';

// Import assets, consumables and vendors from a file (WP-049b S4b; REQ-AST-053): upload, a dry
// run that changes nothing (what would be added and updated, and each row's problem), then the
// real run. Both steps run on the server; their progress arrives live on the person's channel.

const KINDS: AssetImportKind[] = ['assets', 'consumables', 'vendors'];
const MODES: AssetImportMode[] = ['add_update', 'add', 'update'];
const MATCHES: Record<AssetImportKind, AssetImportMatch[]> = {
  assets: ['serial_number', 'tag'],
  consumables: ['product'],
  vendors: ['name'],
};
const MAX_BYTES = 5 * 1024 * 1024;
function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function ImportProgress({
  job,
  onRun,
  running,
}: {
  job: AssetImport;
  onRun: () => void;
  running: boolean;
}) {
  const t = useLabel();
  const busy = job.status === 'queued' || job.status === 'running';
  const percent = job.total === 0 ? 0 : Math.round((job.processed / job.total) * 100);
  const counts = {
    created: job.created_count,
    updated: job.updated_count,
    failed: job.failed_count,
  };
  return (
    <Flex vertical gap={12} data-testid="asset-import-progress">
      <Typography.Text strong>{t(`asset_import_status.${job.status}`)}</Typography.Text>
      {busy && (
        <>
          <Progress percent={percent} />
          <Typography.Text>
            {t(job.dry_run ? 'assets.import.checking' : 'assets.import.importing', {
              processed: job.processed,
              total: job.total,
            })}
          </Typography.Text>
        </>
      )}
      {job.status === 'failed' && (
        <Alert
          type="error"
          showIcon
          message={failureText(t, job)}
          data-testid="asset-import-failure"
        />
      )}
      {job.status === 'checked' && (
        <>
          <Typography.Text data-testid="asset-import-would">
            {t('assets.import.would', counts)}
          </Typography.Text>
          <Typography.Text type="secondary">{t('assets.import.nothing_changed')}</Typography.Text>
        </>
      )}
      {job.status === 'done' && (
        <Typography.Text data-testid="asset-import-did">
          {t('assets.import.did', counts)}
        </Typography.Text>
      )}
      {job.problems.length > 0 && (
        <>
          <Table<AssetImportProblem>
            size="small"
            rowKey={(row) => `${String(row.row)}-${row.field ?? ''}-${row.code}`}
            pagination={{ pageSize: 10, hideOnSinglePage: true }}
            dataSource={job.problems}
            data-testid="asset-import-problems"
            columns={[
              { key: 'row', title: t('assets.import.row'), render: (_, row) => row.row },
              {
                key: 'column',
                title: t('assets.import.column'),
                render: (_, row) => columnText(t, row.field),
              },
              {
                key: 'problem',
                title: t('assets.import.problem'),
                render: (_, row) => reasonText(t, row.code, row.field),
              },
            ]}
          />
          <Button
            onClick={() => {
              download(`${t('assets.import.problems_file')}.csv`, problemsCsv(t, job.problems));
            }}
            data-testid="asset-import-download-problems"
          >
            {t('assets.import.download_problems')}
          </Button>
        </>
      )}
      {job.status === 'checked' && (
        <WriteButton
          type="primary"
          loading={running}
          onClick={onRun}
          data-testid="asset-import-run"
        >
          {t('assets.import.run')}
        </WriteButton>
      )}
    </Flex>
  );
}

/**
 * The import wizard: what the file holds, how rows match, the file; then the dry run's result;
 * then the run. Assets and consumables need assets.manage, vendors their own rights; the server
 * decides, and says so if not.
 */
export function ImportWizard({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useLabel();
  const access = useAccess();
  const queryClient = useQueryClient();
  const start = useStartAssetImport();
  const runImport = useRunAssetImport();
  const [kind, setKind] = useState<AssetImportKind>('assets');
  const [mode, setMode] = useState<AssetImportMode>('add_update');
  const [matchOn, setMatchOn] = useState<AssetImportMatch>('serial_number');
  const [file, setFile] = useState<File>();
  const [jobId, setJobId] = useState<string>();
  const [problem, setProblem] = useState<string | null>(null);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const input = useRef<HTMLInputElement>(null);
  const job = useAssetImport(jobId);
  usePersonalChannel((message) => {
    if (jobId === undefined || message.type !== ASSET_IMPORT_PROGRESS) return;
    if (!message.ids.includes(jobId)) return;
    void queryClient.invalidateQueries({ queryKey: assetBatchKeys.import(jobId) });
    // Rows that were applied show in the list: refetch it once the import is done.
    void queryClient.invalidateQueries({ queryKey: [...queryKeys.assets.all, 'records'] });
  });
  const kinds = KINDS.filter((k) =>
    k === 'vendors' ? access.can('vendors.create') || access.can('vendors.manage') : true,
  );
  const reset = () => {
    setFile(undefined);
    setJobId(undefined);
    setProblem(null);
    setKey(crypto.randomUUID());
  };
  const close = () => {
    reset();
    onClose();
  };
  const check = () => {
    if (file === undefined) return;
    setProblem(null);
    if (file.size > MAX_BYTES) {
      setProblem(t('errors.asset_import_file_too_large'));
      return;
    }
    start.mutate(
      { key, file, kind, mode, matchOn },
      {
        onSuccess: (made) => {
          setJobId(made.id);
        },
        onError: (error) => {
          setProblem(problemText(t, error));
        },
      },
    );
  };
  const run = () => {
    if (job.data === undefined) return;
    setProblem(null);
    runImport.mutate(
      { id: job.data.id, version: job.data.version },
      {
        onError: (error) => {
          setProblem(problemText(t, error));
        },
      },
    );
  };
  const current = job.data;
  const step = current === undefined ? 0 : current.dry_run ? 1 : 2;
  return (
    <Drawer
      open={open}
      title={t('assets.import.title')}
      width="min(640px, 100vw)"
      destroyOnHidden
      onClose={close}
      data-testid="asset-import-drawer"
    >
      <Flex vertical gap={16}>
        <Steps
          size="small"
          current={step}
          items={[
            { title: t('assets.import.step_upload') },
            { title: t('assets.import.step_check') },
            { title: t('assets.import.step_run') },
          ]}
        />
        {problem !== null && (
          <Alert type="error" showIcon message={problem} data-testid="asset-import-problem" />
        )}
        {current === undefined ? (
          <Form layout="vertical" component="div">
            <Form.Item label={t('assets.import.kind')}>
              <Select
                value={kind}
                onChange={(value: AssetImportKind) => {
                  setKind(value);
                  setMatchOn(MATCHES[value][0] ?? 'name');
                }}
                options={kinds.map((k) => ({ value: k, label: t(`asset_import_kind.${k}`) }))}
                data-testid="asset-import-kind"
              />
            </Form.Item>
            <Form.Item label={t('assets.import.mode')}>
              <Select
                value={mode}
                onChange={setMode}
                options={MODES.map((m) => ({ value: m, label: t(`asset_import_mode.${m}`) }))}
                data-testid="asset-import-mode"
              />
            </Form.Item>
            <Form.Item label={t('assets.import.match')}>
              <Select
                value={matchOn}
                onChange={setMatchOn}
                options={MATCHES[kind].map((m) => ({
                  value: m,
                  label: t(`asset_import_match.${m}`),
                }))}
                data-testid="asset-import-match"
              />
            </Form.Item>
            <Form.Item label={t('assets.import.file')} help={t('assets.import.limits', WORDS)}>
              <input
                ref={input}
                type="file"
                accept=".csv,.txt,.xlsx"
                hidden
                onChange={(event) => {
                  setFile(event.target.files?.[0]);
                }}
                data-testid="asset-import-file"
              />
              <Flex gap={8} align="center" wrap>
                <Button
                  icon={<UploadOutlined />}
                  onClick={() => {
                    input.current?.click();
                  }}
                >
                  {t('assets.import.choose_file')}
                </Button>
                {file !== undefined && <bdi dir="auto">{file.name}</bdi>}
              </Flex>
            </Form.Item>
            <WriteButton
              type="primary"
              disabled={file === undefined}
              whyDisabled={file === undefined ? t('assets.import.choose_file') : undefined}
              loading={start.isPending}
              onClick={check}
              data-testid="asset-import-check"
            >
              {t('assets.import.check')}
            </WriteButton>
          </Form>
        ) : (
          <>
            <ImportProgress job={current} onRun={run} running={runImport.isPending} />
            {(current.status === 'done' || current.status === 'failed') && (
              <Button onClick={reset} data-testid="asset-import-again">
                {t('assets.import.again')}
              </Button>
            )}
          </>
        )}
      </Flex>
    </Drawer>
  );
}
