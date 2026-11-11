import { useQueryClient } from '@tanstack/react-query';
import { Alert, App, Collapse, Flex, Form, Input, Skeleton, Space, Table, Typography } from 'antd';
import { useMemo, useRef } from 'react';

import {
  useRecordWorkflows,
  useRestartInstance,
  useRetryInstance,
  useStopInstance,
  type RecordWorkflowOut,
} from '@supportx/api-client';
import {
  Background,
  ReactFlow,
  ReactFlowProvider,
  readDefinition,
  toGraph,
  type WorkflowNode,
} from '@supportx/flow';
import { useRecordEvents } from '@supportx/realtime';
import {
  EmptyText,
  ToneTag,
  WriteButton,
  lengthLimit,
  reportError,
  useAccess,
  useAppearance,
  useDateTime,
  useLabel,
} from '@supportx/ui';

import { NodeView } from '../admin/workflows/NodeView';
import { isKnownPort } from '../admin/workflows/nodes';

import { failureText, stoppedText } from './failure';

type Run = RecordWorkflowOut;
type Step = Run['steps'][number];

const NODE_TYPES = { workflow: NodeView };
const ACTIVE = new Set(['running', 'waiting', 'failed']);

function statusTone(status: string) {
  return status === 'failed'
    ? ('error' as const)
    : status === 'finished'
      ? ('success' as const)
      : status === 'cancelled'
        ? ('default' as const)
        : ('info' as const);
}

/** The run's diagram, read only: the path taken and where it is now marked (REQ-WF-023). */
function Diagram({ run }: { run: Run }) {
  const t = useLabel();
  const { direction, mode } = useAppearance();
  const graph = useMemo(() => {
    const definition = readDefinition(run.definition);
    const passed = new Set(run.steps.map((s) => s.node));
    const at = new Set(run.current_nodes);
    // The outputs drawn are the ones its links use: a read-only diagram needs nothing else.
    const used = (id: string) => [
      ...new Set(definition.links.filter((l) => l.from === id).map((l) => l.port)),
    ];
    const drawn = toGraph(definition, { ports: (n) => used(n.id), rtl: direction === 'rtl' });
    return {
      edges: drawn.edges,
      nodes: drawn.nodes.map((n): WorkflowNode => ({
        ...n,
        data: {
          ...n.data,
          state: at.has(n.id) ? 'current' : passed.has(n.id) ? 'passed' : undefined,
        },
      })),
    };
  }, [run, direction]);
  return (
    <div
      style={{ height: 320, minWidth: 0 }}
      role="img"
      aria-label={t('workflows.record.diagram', { name: run.workflow_name })}
      data-testid={`record-workflow-diagram-${run.instance.id}`}
    >
      <ReactFlowProvider>
        <ReactFlow
          nodes={graph.nodes}
          edges={graph.edges}
          nodeTypes={NODE_TYPES}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          fitView
          colorMode={mode === 'dark' ? 'dark' : 'light'}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={20} />
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  );
}

/** The run's log (REQ-WF-023 AC2): every step with its result, time to the second, duration. */
function StepLog({ run }: { run: Run }) {
  const t = useLabel();
  const dates = useDateTime();
  const rows = run.steps.map((s, i) => ({ ...s, next: run.steps[i + 1]?.at }));
  return (
    <Table<Step & { next?: string }>
      size="small"
      rowKey="seq"
      pagination={false}
      dataSource={rows}
      scroll={{ x: 560 }}
      locale={{ emptyText: <EmptyText>{t('workflows.record.no_steps')}</EmptyText> }}
      data-testid={`record-workflow-log-${run.instance.id}`}
      columns={[
        {
          key: 'node',
          title: t('workflows.record.step'),
          render: (_, s) =>
            t('workflows.test.step', {
              type: t(`workflow_node_type.${s.node_type}`),
              node: s.node,
            }),
        },
        {
          key: 'result',
          title: t('workflows.record.result'),
          render: (_, s) => (isKnownPort(s.result) ? t(`workflow_port.${s.result}`) : '—'),
        },
        {
          key: 'at',
          title: t('workflows.record.at'),
          render: (_, s) => dates.formatExact(s.at),
        },
        {
          key: 'took',
          title: t('workflows.record.took'),
          render: (_, s) => {
            if (s.next === undefined) return '—';
            const seconds = Math.max(
              0,
              Math.round((new Date(s.next).getTime() - new Date(s.at).getTime()) / 1000),
            );
            return t('workflows.record.seconds', { n: seconds });
          },
        },
      ]}
    />
  );
}

function RunActions({ run }: { run: Run }) {
  const t = useLabel();
  const { modal } = App.useApp();
  const stop = useStopInstance();
  const restart = useRestartInstance();
  const retry = useRetryInstance();
  // The confirm dialog reads the reason when it closes: a ref, not state its callback captured.
  const reason = useRef('');
  const i = run.instance;
  if (!ACTIVE.has(i.status) && i.status !== 'cancelled' && i.status !== 'finished') return null;
  return (
    <Space wrap>
      {i.status === 'failed' && (
        <WriteButton
          type="primary"
          size="small"
          loading={retry.isPending}
          onClick={() => {
            retry.mutate({ id: i.id, version: i.version }, { onError: reportError });
          }}
          data-testid={`record-workflow-retry-${i.id}`}
        >
          {t('workflows.record.retry')}
        </WriteButton>
      )}
      <WriteButton
        size="small"
        loading={restart.isPending}
        onClick={() => {
          restart.mutate({ id: i.id, version: i.version }, { onError: reportError });
        }}
        data-testid={`record-workflow-restart-${i.id}`}
      >
        {t('workflows.record.restart')}
      </WriteButton>
      {ACTIVE.has(i.status) && (
        <WriteButton
          size="small"
          danger
          onClick={() => {
            reason.current = '';
            void modal.confirm({
              title: t('workflows.record.stop_title', { name: run.workflow_name }),
              content: (
                <Form layout="vertical">
                  <Form.Item
                    label={t('workflows.record.stop_reason')}
                    htmlFor="stop-reason"
                    required
                  >
                    <Input.TextArea
                      id="stop-reason"
                      rows={3}
                      count={lengthLimit(500)}
                      onChange={(e) => {
                        reason.current = e.target.value;
                      }}
                      data-testid="record-workflow-stop-reason"
                    />
                  </Form.Item>
                </Form>
              ),
              okText: t('workflows.record.stop'),
              okButtonProps: { danger: true },
              cancelText: t('actions.cancel'),
              onOk: () =>
                stop
                  .mutateAsync({ id: i.id, version: i.version, reason: reason.current.trim() })
                  .catch(reportError),
            });
          }}
          data-testid={`record-workflow-stop-${i.id}`}
        >
          {t('workflows.record.stop')}
        </WriteButton>
      )}
    </Space>
  );
}

/**
 * A record's Workflows panel (WP-048b S4d; REQ-WF-023, -024, -026): each run with its diagram
 * (the path taken and where it is now), its log, a banner naming the step and the error when it
 * failed, and retry, run again and stop. For people with workflows.run who may see the record
 * (the server's gate); requesters never get it. Live: a run that moves reaches the record's
 * channel and the panel refetches (REQ-WF-023 AC1).
 */
export function RecordWorkflows({
  recordType,
  recordId,
}: {
  recordType: string;
  recordId: string;
}) {
  const t = useLabel();
  const dates = useDateTime();
  const { can } = useAccess();
  const queryClient = useQueryClient();
  const allowed = can('workflows.run') || can('workflows.manage');
  const runs = useRecordWorkflows(recordType, recordId, allowed);
  useRecordEvents('wi', allowed ? recordId : undefined, (m) => {
    if (m.type === 'workflow_instances.changed') {
      void queryClient.invalidateQueries({
        queryKey: ['workflows', 'record', recordType, recordId],
      });
    }
  });
  if (!allowed) return null;
  if (runs.isPending) return <Skeleton active />;
  const list = runs.data ?? [];
  if (list.length === 0) {
    return <EmptyText>{t('workflows.record.none')}</EmptyText>;
  }
  return (
    <Collapse
      defaultActiveKey={[list[0]?.instance.id ?? '']}
      data-testid="record-workflows"
      items={list.map((run) => {
        const i = run.instance;
        const failure = i.failure as {
          node?: string;
          code?: string;
          params?: Record<string, unknown>;
        } | null;
        return {
          key: i.id,
          label: (
            <Flex gap={8} align="center" wrap>
              <Typography.Text strong>
                <bdi dir="auto">{run.workflow_name}</bdi>
              </Typography.Text>
              <ToneTag tone={statusTone(i.status)} testId={`record-workflow-status-${i.id}`}>
                {t(`workflow_instance_status.${i.status}`)}
              </ToneTag>
              <Typography.Text type="secondary">
                {t('workflows.record.started', { date: dates.format(i.started_at) })}
              </Typography.Text>
            </Flex>
          ),
          children: (
            <Flex vertical gap={12}>
              {i.status === 'failed' && failure !== null && (
                <Alert
                  type="error"
                  showIcon
                  message={t('workflows.record.failed_at', { node: failure.node ?? '' })}
                  description={failureText(t, failure.code ?? '', failure.params ?? {})}
                  data-testid={`record-workflow-failure-${i.id}`}
                />
              )}
              {i.status === 'cancelled' && typeof i.stopped_reason === 'string' && (
                <Alert
                  type="info"
                  showIcon
                  message={t('workflows.record.stopped')}
                  description={<bdi dir="auto">{stoppedText(t, i.stopped_reason)}</bdi>}
                />
              )}
              <RunActions run={run} />
              <Diagram run={run} />
              <StepLog run={run} />
            </Flex>
          ),
        };
      })}
    />
  );
}
