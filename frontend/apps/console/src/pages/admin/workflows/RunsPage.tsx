import { useQueryClient } from '@tanstack/react-query';
import {
  App,
  Button,
  Flex,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Table,
  Typography,
} from 'antd';
import { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  useQueueJob,
  useWorkflowRuns,
  useWorkflows,
  type OverviewRunOut,
  type RunsQuery,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { useListChannel } from '@supportx/realtime';
import {
  FilterBar,
  FiltersDrawer,
  ListPage,
  NoAccess,
  PageHeader,
  SectionNav,
  ToneTag,
  WriteButton,
  lengthLimit,
  loadedEmpty,
  reportError,
  useAccess,
  useDateTime,
  useLabel,
  usePageCrumbs,
} from '@supportx/ui';

import { failureText } from '../../workflows/failure';
import { JobProgress } from './JobProgress';
import { WORKFLOW_TYPES, type WorkflowType } from './types';

const STATES = ['failed', 'waiting', 'running', 'finished', 'cancelled'] as const;
// Where a job's record path starts, per record type (the run's record link).
const RECORD_PATH: Record<string, string> = {
  incident: '/incidents',
  service_request: '/requests',
  problem: '/problems',
  change: '/changes',
  release: '/releases',
};
const LIVE = new Set(['running', 'waiting', 'failed']);

/** The Workflows admin's two tabs: the workflows themselves and their runs. */
export function WorkflowsNav({ active }: { active: 'list' | 'runs' }) {
  const t = useLabel();
  const navigate = useNavigate();
  return (
    <SectionNav
      label={t('nav.admin_workflows')}
      active={active}
      onNavigate={(path) => void navigate(path)}
      items={[
        { key: 'list', label: t('workflows.tab.list'), path: '/admin/workflows' },
        { key: 'runs', label: t('workflows.tab.runs'), path: '/admin/workflows/runs' },
      ]}
      testId="workflows-sections"
    />
  );
}

function statusTone(status: string) {
  return status === 'failed'
    ? ('error' as const)
    : status === 'finished'
      ? ('success' as const)
      : status === 'cancelled'
        ? ('default' as const)
        : ('info' as const);
}

/**
 * Admin › Workflows › Runs (WP-048b S5a; REQ-WF-025; template C): every run of the tenant,
 * newest first, by workflow, state and step; how long it has waited; failures in words. A
 * run's record is named and linked only when you may see it. Selected runs are retried or
 * cancelled (with a reason) as background jobs, one per workflow, with live progress.
 */
export function RunsPage() {
  const t = useLabel();
  const dates = useDateTime();
  const list = useListFormat();
  const { can } = useAccess();
  const { modal, message } = App.useApp();
  const queryClient = useQueryClient();
  const allowed = can('workflows.manage');
  const [recordType, setRecordType] = useState<WorkflowType>('incident');
  const [query, setQuery] = useState<RunsQuery>({ status: 'failed' });
  const [drawer, setDrawer] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [jobs, setJobs] = useState<string[]>([]);
  const reason = useRef('');
  const runs = useWorkflowRuns(query, allowed);
  const flows = useWorkflows(recordType, allowed);
  const queue = useQueueJob();
  usePageCrumbs([
    { label: t('nav.admin_workflows'), path: '/admin/workflows' },
    { label: t('workflows.tab.runs') },
  ]);
  useListChannel(allowed ? 'workflows' : null, (m) => {
    if (m.type === 'workflow_instances.changed') {
      void queryClient.invalidateQueries({ queryKey: ['workflows', 'runs'] });
    }
    if (m.type === 'workflow_jobs.changed') {
      for (const id of m.ids) {
        void queryClient.invalidateQueries({ queryKey: ['workflows', 'job', id] });
      }
    }
  });
  if (!allowed) return <NoAccess titleKey="nav.admin_workflows" />;

  const rows = runs.data?.items ?? [];
  const chosen = rows.filter((r) => selected.includes(r.id));
  const drawerCount = [query.node, query.waitingOverHours].filter(
    (v) => v !== undefined && v !== '',
  ).length;

  // One job per workflow: a job acts on runs of its own workflow (S3b).
  const bulk = (kind: 'retry' | 'cancel', why?: string) => {
    const byFlow = new Map<string, string[]>();
    for (const r of chosen) byFlow.set(r.workflow_id, [...(byFlow.get(r.workflow_id) ?? []), r.id]);
    for (const [workflowId, ids] of byFlow) {
      queue.mutate(
        {
          workflowId,
          key: crypto.randomUUID(),
          body: { kind, instance_ids: ids, dry_run: false, reason: why ?? null },
        },
        {
          onSuccess: (job) => {
            setJobs((now) => [...now, job.id]);
          },
          onError: reportError,
        },
      );
    }
    setSelected([]);
    void message.info(t('workflows.runs.queued'));
  };
  const askCancel = () => {
    reason.current = '';
    void modal.confirm({
      title: t('workflows.runs.cancel_title', { count: chosen.length }),
      content: (
        <Form layout="vertical">
          <Form.Item
            label={t('workflows.record.stop_reason')}
            htmlFor="runs-cancel-reason"
            required
          >
            <Input.TextArea
              id="runs-cancel-reason"
              rows={3}
              count={lengthLimit(500)}
              onChange={(e) => {
                reason.current = e.target.value;
              }}
              data-testid="runs-cancel-reason"
            />
          </Form.Item>
        </Form>
      ),
      okText: t('workflows.runs.cancel'),
      okButtonProps: { danger: true },
      cancelText: t('actions.cancel'),
      onOk: () => {
        const why = reason.current.trim();
        if (why === '') {
          void message.error(t('workflows.runs.reason_needed'));
          return Promise.reject(new Error('reason'));
        }
        bulk('cancel', why);
        return Promise.resolve();
      },
    });
  };

  const selectionBar =
    chosen.length > 0 ? (
      <Space wrap data-testid="runs-selection">
        <Typography.Text>{t('workflows.runs.selected', { count: chosen.length })}</Typography.Text>
        <WriteButton
          disabled={!chosen.every((r) => r.status === 'failed')}
          whyDisabled={t('workflows.runs.why.retry_failed_only')}
          onClick={() => {
            bulk('retry');
          }}
          data-testid="runs-retry"
        >
          {t('workflows.record.retry')}
        </WriteButton>
        <WriteButton danger onClick={askCancel} data-testid="runs-cancel">
          {t('workflows.runs.cancel')}
        </WriteButton>
        <Button
          type="link"
          onClick={() => {
            setSelected([]);
          }}
        >
          {t('workflows.runs.clear_selection')}
        </Button>
      </Space>
    ) : undefined;

  return (
    <ListPage
      testId="workflow-runs"
      header={
        <Flex vertical gap={8}>
          <PageHeader
            title={t('nav.admin_workflows')}
            count={
              runs.data?.estimated_total === undefined || runs.data.estimated_total === null
                ? undefined
                : String(runs.data.estimated_total)
            }
            testId="workflow-runs-header"
          />
          <WorkflowsNav active="runs" />
        </Flex>
      }
      filters={
        <>
          <FilterBar
            testId="runs-filters"
            selection={selectionBar}
            view={
              <Select<string>
                style={{ minWidth: 180 }}
                prefix={`${t('workflows.state.title')}:`}
                aria-label={t('workflows.state.title')}
                value={query.status ?? 'all'}
                onChange={(status) => {
                  setQuery({ ...query, status: status === 'all' ? undefined : status });
                }}
                options={[
                  { value: 'all', label: t('workflows.runs.all') },
                  ...STATES.map((s) => ({ value: s, label: t(`workflow_instance_status.${s}`) })),
                ]}
                data-testid="runs-status"
              />
            }
            quick={
              <>
                <Select<WorkflowType>
                  style={{ minWidth: 170 }}
                  aria-label={t('workflows.record_type')}
                  value={recordType}
                  onChange={(next) => {
                    setRecordType(next);
                    setQuery({ ...query, workflowId: undefined });
                  }}
                  options={WORKFLOW_TYPES.map((v) => ({
                    value: v,
                    label: t(`work_item_type.${v}`),
                  }))}
                  data-testid="runs-record-type"
                />
                <Select<string>
                  allowClear
                  style={{ minWidth: 200 }}
                  aria-label={t('workflows.type_label')}
                  placeholder={t('workflows.runs.any_workflow')}
                  value={query.workflowId}
                  onChange={(workflowId: string | undefined) => {
                    setQuery({ ...query, workflowId });
                  }}
                  options={(flows.data ?? []).map((w) => ({ value: w.id, label: w.name }))}
                  data-testid="runs-workflow"
                />
              </>
            }
            filtersCount={drawerCount}
            onOpenFilters={() => {
              setDrawer(true);
            }}
          />
          <FiltersDrawer
            open={drawer}
            onClose={() => {
              setDrawer(false);
            }}
            onReset={() => {
              setQuery({ ...query, node: undefined, waitingOverHours: undefined });
            }}
            testId="runs-drawer"
          >
            <Form layout="vertical">
              <Form.Item label={t('workflows.runs.step')} htmlFor="runs-node">
                <Input
                  id="runs-node"
                  dir="ltr"
                  allowClear
                  value={query.node ?? ''}
                  onChange={(e) => {
                    setQuery({
                      ...query,
                      node: e.target.value === '' ? undefined : e.target.value,
                    });
                  }}
                  data-testid="runs-node"
                />
              </Form.Item>
              <Form.Item
                label={t('workflows.runs.waiting_over')}
                htmlFor="runs-waiting"
                help={t('workflows.runs.waiting_over_help')}
              >
                <InputNumber<number>
                  id="runs-waiting"
                  min={1}
                  max={24 * 366}
                  precision={0}
                  value={query.waitingOverHours ?? null}
                  onChange={(hours) => {
                    setQuery({ ...query, waitingOverHours: hours ?? undefined });
                  }}
                  data-testid="runs-waiting"
                />
              </Form.Item>
            </Form>
          </FiltersDrawer>
        </>
      }
      alerts={
        jobs.length > 0 && (
          <Flex vertical gap={8} data-testid="runs-jobs">
            {jobs.map((id) => (
              <JobProgress
                key={id}
                id={id}
                onDone={() => {
                  setJobs((now) => now.filter((j) => j !== id));
                  void queryClient.invalidateQueries({ queryKey: ['workflows', 'runs'] });
                }}
              />
            ))}
          </Flex>
        )
      }
    >
      <Table<OverviewRunOut>
        rowKey="id"
        data-testid="runs-table"
        loading={runs.isPending}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 900 }}
        rowSelection={{
          selectedRowKeys: selected,
          onChange: (keys) => {
            setSelected(keys.map(String));
          },
          getCheckboxProps: (r) => ({
            disabled: !LIVE.has(r.status),
            'aria-label': t('workflows.runs.select', { name: r.workflow_name }),
          }),
        }}
        locale={{ emptyText: loadedEmpty(runs.isPending, t('workflows.runs.none')) }}
        columns={[
          {
            key: 'record',
            title: t('workflows.runs.record'),
            render: (_, r) =>
              r.record === null || r.record === undefined ? (
                <Typography.Text type="secondary">
                  {t('workflows.runs.hidden_record')}
                </Typography.Text>
              ) : (
                <Link
                  to={`${RECORD_PATH[r.record_type] ?? ''}/${r.record_id}`}
                  data-testid={`run-record-${r.id}`}
                >
                  <bdi dir="ltr">{r.record.display_id}</bdi> ·{' '}
                  <bdi dir="auto">{r.record.subject}</bdi>
                </Link>
              ),
          },
          {
            key: 'workflow',
            title: t('workflows.type_label'),
            render: (_, r) => <bdi dir="auto">{r.workflow_name}</bdi>,
          },
          {
            key: 'state',
            title: t('workflows.state.title'),
            render: (_, r) => (
              <ToneTag tone={statusTone(r.status)}>
                {t(`workflow_instance_status.${r.status}`)}
              </ToneTag>
            ),
          },
          {
            key: 'step',
            title: t('workflows.runs.step'),
            render: (_, r) => {
              const failure = r.failure as { node?: string; code?: string } | null;
              if (r.status === 'failed' && failure !== null) {
                return (
                  <Flex vertical>
                    <bdi dir="ltr">{failure.node ?? ''}</bdi>
                    <Typography.Text type="danger" style={{ fontSize: 12 }}>
                      {failureText(t, failure.code ?? '')}
                    </Typography.Text>
                  </Flex>
                );
              }
              return <bdi dir="ltr">{list(r.current_nodes ?? [])}</bdi>;
            },
          },
          {
            key: 'started',
            title: t('workflows.runs.started'),
            render: (_, r) => (
              <span title={dates.format(r.started_at)}>{dates.relative(r.started_at)}</span>
            ),
          },
        ]}
      />
    </ListPage>
  );
}
