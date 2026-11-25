import { UploadOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Flex, Form, Progress, Select, Steps, Table, Typography } from 'antd';
import { useRef, useState } from 'react';

import {
  CI_IMPORT_PROGRESS,
  ciImportProblemsUrl,
  ciMergeKeys,
  queryKeys,
  useCiImport,
  useCiTypes,
  useRunCiImport,
  useStartCiImport,
  type CiImport,
  type CiImportKind,
  type CiImportMatch,
  type CiImportMode,
  type CiImportProblem,
} from '@supportx/api-client';
import { usePersonalChannel } from '@supportx/realtime';
import { Drawer, useAppearance, useLabel, WriteButton } from '@supportx/ui';

import { problemText } from '../assets/problemText';
import { nameOf } from './names';

// Import CIs or relationships from a file (WP-053 S4b; REQ-CMDB-018), as the assets' import:
// upload, a dry run that changes nothing (what would be added, updated or left as it is, and
// each row's problem), then the real run. Both run on the server; progress arrives live on the
// person's own channel. The refused rows download is the server's, in your language and
// formula-safe.

const KINDS: CiImportKind[] = ['cis', 'relationships'];
const MODES: CiImportMode[] = ['add_update', 'add', 'update'];
const MATCHES: CiImportMatch[] = ['name', 'display_id'];
const MAX_MEGABYTES = 25;
const LIMITS = { max_rows: '20,000', max_megabytes: MAX_MEGABYTES };

function fieldText(t: ReturnType<typeof useLabel>, field: string | null) {
  return t(`cmdb_import_field.${field ?? 'row'}`);
}

function ImportProgress({
  job,
  onRun,
  running,
}: {
  job: CiImport;
  onRun: () => void;
  running: boolean;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const busy = job.status === 'queued' || job.status === 'running';
  const percent = job.total === 0 ? 0 : Math.round((job.processed / job.total) * 100);
  const counts = {
    created: job.created_count,
    updated: job.updated_count,
    unchanged: job.unchanged_count,
    failed: job.failed_count,
  };
  const language = locale === 'ar' || locale === 'ur' ? locale : 'en';
  return (
    <Flex vertical gap={12} data-testid="ci-import-progress">
      <Typography.Text strong>{t(`cmdb_import_status.${job.status}`)}</Typography.Text>
      {busy && (
        <>
          <Progress percent={percent} />
          <Typography.Text>
            {t('cmdb.import.progress', { processed: job.processed, total: job.total })}
          </Typography.Text>
        </>
      )}
      {job.status === 'failed' && job.failure !== null && (
        <Alert
          type="error"
          showIcon
          message={t(`errors.${job.failure}`, LIMITS)}
          data-testid="ci-import-failure"
        />
      )}
      {job.status === 'checked' && (
        <>
          <Typography.Text data-testid="ci-import-would">
            {t('cmdb.import.would', counts)}
          </Typography.Text>
          <Typography.Text type="secondary">{t('cmdb.import.nothing_changed')}</Typography.Text>
        </>
      )}
      {job.status === 'done' && (
        <Typography.Text data-testid="ci-import-did">
          {t('cmdb.import.did', counts)}
        </Typography.Text>
      )}
      {(job.status === 'checked' || job.status === 'done') && job.kept_count > 0 && (
        // S4a's who wins: rows whose values a higher-ranked source (by default, a hand edit) set.
        <Typography.Text type="secondary" data-testid="ci-import-kept">
          {t('cmdb.import.kept', { kept: job.kept_count })}
        </Typography.Text>
      )}
      {job.problems.length > 0 && (
        <>
          <Table<CiImportProblem>
            size="small"
            rowKey={(row) => `${String(row.row)}-${row.field ?? ''}-${row.code}`}
            pagination={{ pageSize: 10, hideOnSinglePage: true }}
            dataSource={job.problems}
            data-testid="ci-import-problems"
            columns={[
              { key: 'row', title: t('cmdb.import.column.row'), render: (_, row) => row.row },
              {
                key: 'column',
                title: t('cmdb.import.column.field'),
                render: (_, row) => fieldText(t, row.field),
              },
              {
                key: 'problem',
                title: t('cmdb.import.column.problem'),
                render: (_, row) => t(`errors.field.${row.code}`),
              },
            ]}
          />
          <Button
            href={ciImportProblemsUrl(job.id, language)}
            download
            data-testid="ci-import-download-problems"
          >
            {t('cmdb.import.download_problems')}
          </Button>
        </>
      )}
      {job.status === 'checked' && (
        <WriteButton type="primary" loading={running} onClick={onRun} data-testid="ci-import-run">
          {t('cmdb.import.run')}
        </WriteButton>
      )}
    </Flex>
  );
}

/**
 * The import drawer: what the file holds, how rows name CIs, the CIs' type, the file; then the
 * dry run's result; then the run. The server decides who may (cmdb.add to add, cmdb.edit to
 * update, cmdb.manage for both), and rows only ever match CIs the importer may see.
 */
export function CiImportDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const queryClient = useQueryClient();
  const types = useCiTypes(open);
  const start = useStartCiImport();
  const runImport = useRunCiImport();
  const [kind, setKind] = useState<CiImportKind>('cis');
  const [mode, setMode] = useState<CiImportMode>('add_update');
  const [matchOn, setMatchOn] = useState<CiImportMatch>('name');
  const [typeId, setTypeId] = useState<string>();
  const [file, setFile] = useState<File>();
  const [jobId, setJobId] = useState<string>();
  const [problem, setProblem] = useState<string | null>(null);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const input = useRef<HTMLInputElement>(null);
  const job = useCiImport(jobId);
  usePersonalChannel(
    (message) => {
      if (message.covered === true) return; // a refresh: `covers` refetched the job
      if (jobId === undefined || message.type !== CI_IMPORT_PROGRESS) return;
      if (!message.ids.includes(jobId)) return;
      void queryClient.invalidateQueries({ queryKey: ciMergeKeys.import(jobId) });
      // Rows that were applied reach the lists through their own events; refetch to be sure.
      void queryClient.invalidateQueries({ queryKey: [...queryKeys.cmdb.all, 'list'] });
    },
    // The drawer shows only its import job (the list behind it covers itself).
    { covers: jobId === undefined ? [] : [ciMergeKeys.import(jobId)] },
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
  const needsType = kind === 'cis';
  const ready = file !== undefined && (!needsType || typeId !== undefined);
  const check = () => {
    if (file === undefined) return;
    setProblem(null);
    if (file.size > MAX_MEGABYTES * 1024 * 1024) {
      setProblem(t('errors.cmdb_import_file_too_large', LIMITS));
      return;
    }
    start.mutate(
      { key, file, kind, mode, matchOn, typeId: needsType ? typeId : undefined },
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
      title={t('cmdb.import.title')}
      width="min(640px, 100vw)"
      destroyOnHidden
      onClose={close}
      data-testid="ci-import-drawer"
    >
      <Flex vertical gap={16}>
        <Steps
          size="small"
          current={step}
          items={[
            { title: t('cmdb.import.step_upload') },
            { title: t('cmdb.import.step_check') },
            { title: t('cmdb.import.step_run') },
          ]}
        />
        {problem !== null && (
          <Alert type="error" showIcon message={problem} data-testid="ci-import-problem" />
        )}
        {current === undefined ? (
          <Form layout="vertical" component="div">
            <Form.Item label={t('cmdb.import.kind')} help={t(`cmdb.import.columns_${kind}`)}>
              <Select
                value={kind}
                onChange={setKind}
                options={KINDS.map((k) => ({ value: k, label: t(`cmdb_import_kind.${k}`) }))}
                data-testid="ci-import-kind"
              />
            </Form.Item>
            {needsType && (
              <>
                <Form.Item label={t('cmdb.import.type')}>
                  <Select
                    value={typeId}
                    onChange={setTypeId}
                    placeholder={t('cmdb.import.type_placeholder')}
                    loading={types.isPending}
                    options={(types.data?.items ?? []).map((x) => ({
                      value: x.id,
                      label: nameOf(t, locale, x, 'cmdb_ci_type'),
                    }))}
                    data-testid="ci-import-type"
                  />
                </Form.Item>
                <Form.Item label={t('cmdb.import.mode')}>
                  <Select
                    value={mode}
                    onChange={setMode}
                    options={MODES.map((m) => ({ value: m, label: t(`cmdb_import_mode.${m}`) }))}
                    data-testid="ci-import-mode"
                  />
                </Form.Item>
              </>
            )}
            <Form.Item label={t('cmdb.import.match')}>
              <Select
                value={matchOn}
                onChange={setMatchOn}
                options={MATCHES.map((m) => ({ value: m, label: t(`cmdb_import_match.${m}`) }))}
                data-testid="ci-import-match"
              />
            </Form.Item>
            <Form.Item label={t('cmdb.import.file')} help={t('cmdb.import.limits', LIMITS)}>
              <input
                ref={input}
                type="file"
                accept=".csv,.txt,.xlsx"
                // Out of sight and out of the tab order: the styled button below opens it (as
                // the assets' import, QA 2026-11-12 F-03).
                hidden
                style={{ display: 'none' }}
                tabIndex={-1}
                aria-hidden
                onChange={(event) => {
                  setFile(event.target.files?.[0]);
                }}
                data-testid="ci-import-file"
              />
              <Flex gap={8} align="center" wrap>
                <Button
                  icon={<UploadOutlined />}
                  onClick={() => {
                    input.current?.click();
                  }}
                >
                  {t('cmdb.import.choose_file')}
                </Button>
                <Typography.Text
                  type={file === undefined ? 'secondary' : undefined}
                  data-testid="ci-import-file-name"
                >
                  {file === undefined ? (
                    t('cmdb.import.no_file')
                  ) : (
                    <bdi dir="auto">{file.name}</bdi>
                  )}
                </Typography.Text>
              </Flex>
            </Form.Item>
            <WriteButton
              type="primary"
              disabled={!ready}
              whyDisabled={ready ? undefined : t('cmdb.import.not_ready')}
              loading={start.isPending}
              onClick={check}
              data-testid="ci-import-check"
            >
              {t('cmdb.import.check')}
            </WriteButton>
          </Form>
        ) : (
          <>
            <ImportProgress job={current} onRun={run} running={runImport.isPending} />
            {(current.status === 'done' || current.status === 'failed') && (
              <Button onClick={reset} data-testid="ci-import-again">
                {t('cmdb.import.again')}
              </Button>
            )}
          </>
        )}
      </Flex>
    </Drawer>
  );
}
