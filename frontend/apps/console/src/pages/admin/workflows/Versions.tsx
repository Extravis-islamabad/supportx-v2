import { Alert, Flex, Form, List, Select, Space, Typography } from 'antd';
import { useState } from 'react';

import {
  useQueueJob,
  useUser,
  useVersionOccupancy,
  useVersionSteps,
  useWorkflowJob,
  useWorkflowRuns,
  useWorkflowVersions,
  type WorkflowOut,
  type WorkflowVersionOut,
} from '@supportx/api-client';
import {
  EditDialog,
  EmptyText,
  ToneTag,
  WriteButton,
  reportError,
  useDateTime,
  useLabel,
} from '@supportx/ui';

import { failureText } from '../../workflows/failure';
import { JobProgress } from './JobProgress';

const LIVE = ['running', 'waiting', 'failed'];
const MAX_RUNS = 1000; // a job's ceiling (§10)

function Publisher({ id }: { id: string | null }) {
  const t = useLabel();
  const user = useUser(id ?? undefined);
  if (id === null) return <>{t('workflows.versions.by_unknown')}</>;
  return <bdi dir="auto">{user.data?.display_name ?? ''}</bdi>;
}

/**
 * Moving the live runs of one version to the newest (REQ-WF-021): each occupied step is mapped
 * onto a step of the new version; a dry run says what would move and what would stay, and only
 * then can the move be made (the coordinator's S5 terms). Both run as background jobs whose
 * progress shows live.
 */
function MoveDialog({
  workflow,
  from,
  to,
  onClose,
}: {
  workflow: WorkflowOut;
  from: number;
  to: number;
  onClose: () => void;
}) {
  const t = useLabel();
  const occupancy = useVersionOccupancy(workflow.id, from);
  const steps = useVersionSteps(workflow.id, to);
  const runs = useWorkflowRuns({ workflowId: workflow.id, versionNumber: from });
  const queue = useQueueJob();
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [checked, setChecked] = useState<{ job: string; mapping: string }>();
  const [moving, setMoving] = useState<string>();
  const dry = useWorkflowJob(checked?.job ?? '');
  const targets = steps.data ?? [];
  const occupied = Object.entries(occupancy.data ?? {});
  // A step keeps its place by default when the new version has a step of the same id.
  const mapped = (node: string) =>
    mapping[node] ?? (targets.some((s) => s.id === node) ? node : '');
  const plan: Record<string, string> = {};
  for (const [node] of occupied) {
    const target = mapped(node);
    if (target !== '') plan[node] = target;
  }
  const ids = (runs.data?.items ?? [])
    .filter((r) => LIVE.includes(r.status))
    .slice(0, MAX_RUNS)
    .map((r) => r.id);
  const key = JSON.stringify(plan);
  const dryDone = dry.data?.status === 'done' || dry.data?.status === 'failed';
  const readyToMove = checked?.mapping === key && dryDone;
  const send = (dryRun: boolean) => {
    queue.mutate(
      {
        workflowId: workflow.id,
        key: crypto.randomUUID(),
        body: {
          kind: 'migrate',
          instance_ids: ids,
          to_version: to,
          mapping: plan,
          dry_run: dryRun,
          reason: null,
        },
      },
      {
        onSuccess: (job) => {
          if (dryRun) setChecked({ job: job.id, mapping: key });
          else setMoving(job.id);
        },
        onError: reportError,
      },
    );
  };
  const results = dry.data?.results ?? [];
  const would = results.filter((r) => r.outcome === 'would_move').length;
  const stays = results.filter((r) => r.outcome !== 'would_move');
  return (
    <EditDialog
      open
      title={t('workflows.versions.move_title', { from, to })}
      okText={t('workflows.versions.move', { count: would })}
      saving={queue.isPending}
      okDisabled={!readyToMove || would === 0 || moving !== undefined}
      okWhyNot={
        moving !== undefined
          ? t('workflows.versions.why.moving')
          : !readyToMove
            ? t('workflows.versions.why.check_first')
            : t('workflows.versions.why.nothing_moves')
      }
      onCancel={onClose}
      onOk={() => {
        send(false);
      }}
      testId="version-move"
    >
      <Flex vertical gap={12}>
        <Typography.Paragraph type="secondary">
          {t('workflows.versions.move_intro')}
        </Typography.Paragraph>
        {occupied.length === 0 ? (
          <EmptyText>{t('workflows.versions.no_live_runs')}</EmptyText>
        ) : (
          <Form layout="vertical" data-testid="version-mapping">
            {occupied.map(([node, count]) => (
              <Form.Item
                key={node}
                label={t('workflows.versions.map_step', { node, runs: count })}
                htmlFor={`map-${node}`}
              >
                <Select<string>
                  id={`map-${node}`}
                  value={mapped(node)}
                  onChange={(target) => {
                    setMapping({ ...mapping, [node]: target });
                  }}
                  options={[
                    { value: '', label: t('workflows.versions.stays') },
                    ...targets.map((s) => ({
                      value: s.id,
                      label: t('workflows.designer.outline_node', {
                        type: t(`workflow_node_type.${s.type}`),
                        id: s.id,
                      }),
                    })),
                  ]}
                  data-testid={`map-${node}`}
                />
              </Form.Item>
            ))}
          </Form>
        )}
        <Space wrap>
          <WriteButton
            disabled={ids.length === 0 || queue.isPending}
            whyDisabled={t('workflows.versions.no_live_runs')}
            onClick={() => {
              send(true);
            }}
            data-testid="version-dry-run"
          >
            {t('workflows.versions.check')}
          </WriteButton>
          {checked !== undefined && checked.mapping !== key && (
            <Typography.Text type="warning">{t('workflows.versions.check_again')}</Typography.Text>
          )}
        </Space>
        {checked !== undefined && <JobProgress id={checked.job} onDone={() => undefined} />}
        {dryDone && (
          <Alert
            type={stays.length === 0 ? 'success' : 'warning'}
            showIcon
            message={t('workflows.versions.dry_result', { move: would, stay: stays.length })}
            description={
              stays.length > 0 && (
                <List
                  size="small"
                  dataSource={stays.slice(0, 20)}
                  renderItem={(r) => (
                    <List.Item>
                      {failureText(t, typeof r.code === 'string' ? r.code : '', {
                        node: typeof r.node === 'string' ? r.node : '',
                      })}
                    </List.Item>
                  )}
                />
              )
            }
            data-testid="version-dry-result"
          />
        )}
        {moving !== undefined && <JobProgress id={moving} onDone={onClose} />}
      </Flex>
    </EditDialog>
  );
}

/**
 * The designer's Versions tab (REQ-WF-021, -027): every published version, newest first, with
 * who published it, when, and how many runs are still on it. An older version's live runs can
 * be moved to the newest one.
 */
export function VersionsPanel({ workflow }: { workflow: WorkflowOut }) {
  const t = useLabel();
  const dates = useDateTime();
  const versions = useWorkflowVersions(workflow.id);
  const [moving, setMoving] = useState<number>();
  const rows = versions.data ?? [];
  const newest = rows[0]?.number;
  if (rows.length === 0) {
    return <EmptyText>{t('workflows.versions.none')}</EmptyText>;
  }
  return (
    <>
      <List<WorkflowVersionOut>
        dataSource={rows}
        data-testid="workflow-versions"
        renderItem={(v) => (
          <List.Item key={v.number} data-testid={`version-${String(v.number)}`}>
            <Flex vertical gap={2}>
              <Space wrap>
                <Typography.Text strong>
                  {t('workflows.version_n', { n: v.number })}
                </Typography.Text>
                {v.number === newest && (
                  <ToneTag tone="success">{t('workflows.versions.newest')}</ToneTag>
                )}
                <ToneTag tone={v.running > 0 ? 'info' : 'default'}>
                  {t('workflows.versions.live_runs', { count: v.running })}
                </ToneTag>
              </Space>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {dates.format(v.published_at)} · <Publisher id={v.published_by} />
              </Typography.Text>
              {/* Under its text, not in the item's actions: the side panel is narrow, and an
                  action beside the text was cut off (the S5 matrix shot). */}
              {v.number !== newest && v.running > 0 && newest !== undefined && (
                <div>
                  <WriteButton
                    size="small"
                    onClick={() => {
                      setMoving(v.number);
                    }}
                    data-testid={`version-${String(v.number)}-move`}
                  >
                    {t('workflows.versions.move_to', { to: newest })}
                  </WriteButton>
                </div>
              )}
            </Flex>
          </List.Item>
        )}
      />
      {moving !== undefined && newest !== undefined && (
        <MoveDialog
          workflow={workflow}
          from={moving}
          to={newest}
          onClose={() => {
            setMoving(undefined);
          }}
        />
      )}
    </>
  );
}
