import { Button, Card, Checkbox, Flex, List, Space, Typography } from 'antd';
import { useState } from 'react';

import { useRequestTasks, useRequestTaskStatus, type RequestTask } from '@supportx/api-client';
import { reportError, ToneTag, useLabel } from '@supportx/ui';

import { hasPlanParts } from '../incidents/planTask';
import { PlanTaskParts } from '../incidents/PlanTaskParts';

/** Each task's depth: 0 waits for nothing, else one more than its deepest predecessor. */
function depths(rows: RequestTask[]): Map<string, number> {
  const byId = new Map(rows.map((r) => [r.id, r]));
  const found = new Map<string, number>();
  const depth = (id: string, seen: Set<string>): number => {
    const known = found.get(id);
    if (known !== undefined) return known;
    if (seen.has(id)) return 0; // never a loop (the server refuses them): read as a start
    const before = (byId.get(id)?.depends_on ?? []).filter((d) => byId.has(d));
    const next = new Set(seen).add(id);
    const value = before.length === 0 ? 0 : 1 + Math.max(...before.map((d) => depth(d, next)));
    found.set(id, value);
    return value;
  };
  for (const row of rows) depth(row.id, new Set());
  return found;
}

/**
 * The plan as a simple flow (WP-047a S5; REQ-SR-047 AC3): columns by depth, the steps that
 * can start together side by side, each with its state. Live with the task list it reads.
 */
function TaskFlow({ rows }: { rows: RequestTask[] }) {
  const t = useLabel();
  const level = depths(rows);
  const columns: RequestTask[][] = [];
  for (const row of rows) {
    const at = level.get(row.id) ?? 0;
    (columns[at] ??= []).push(row);
  }
  return (
    <Flex gap={12} wrap data-testid="sr-task-flow" aria-label={t('requests.flow.title')}>
      {columns.map((column, at) => (
        <Flex
          key={at}
          vertical
          gap={8}
          style={{ minWidth: 180 }}
          data-testid={`sr-flow-${String(at)}`}
        >
          <Typography.Text type="secondary">
            {t('requests.flow.step', { n: at + 1 })}
          </Typography.Text>
          {column.map((task) => (
            <Card key={task.id} size="small">
              <Flex vertical gap={4}>
                <bdi>{task.title}</bdi>
                <ToneTag
                  tone={
                    task.status === 'done'
                      ? 'success'
                      : task.blocked_by?.length
                        ? 'warning'
                        : 'default'
                  }
                >
                  {task.blocked_by?.length
                    ? t('requests.flow.waiting')
                    : t(`task_status.${task.status}`)}
                </ToneTag>
              </Flex>
            </Card>
          ))}
        </Flex>
      ))}
    </Flex>
  );
}

/**
 * A request's tasks (WP-030 s3, REQ-SR-046, -058): the fulfilment plan's in order, which are
 * required and which internal; ticking one done saves it with If-Match, and the last required
 * one done fulfils the request on the server. Live through the record channel (the page
 * invalidates the record's queries, these included). WP-047a S5: a plan task's own fields, its
 * hand-over (completed with its asset, never by a tick) and the flow of steps that wait.
 */
export function RequestTasks({ recordId, canEdit }: { recordId: string; canEdit: boolean }) {
  const t = useLabel();
  const found = useRequestTasks(recordId);
  const change = useRequestTaskStatus(recordId);
  const [open, setOpen] = useState<string | null>(null);
  const rows = found.data?.items ?? [];
  if (found.isLoading || rows.length === 0) return null;
  const flows = rows.some((r) => (r.depends_on ?? []).length > 0);
  return (
    <Flex vertical gap={12}>
      {flows && <TaskFlow rows={rows} />}
      <List
        header={<Typography.Text strong>{t('requests.tasks')}</Typography.Text>}
        bordered
        dataSource={rows}
        data-testid="sr-tasks"
        renderItem={(task) => {
          const handover = task.kind === 'asset_handover';
          return (
            <List.Item key={task.id} data-testid={`sr-task-${String(task.position)}`}>
              <Flex vertical gap={8} style={{ width: '100%' }}>
                <Space wrap>
                  <Checkbox
                    checked={task.status === 'done'}
                    disabled={
                      !canEdit || change.isPending || task.status === 'canceled' || handover
                    }
                    onChange={(e) => {
                      change.mutate(
                        { task, status: e.target.checked ? 'done' : 'open' },
                        { onError: reportError },
                      );
                    }}
                    aria-label={task.title}
                  >
                    <bdi>{task.title}</bdi>
                  </Checkbox>
                  {task.from_plan && !task.required && (
                    <ToneTag tone="info">{t('requests.task_optional')}</ToneTag>
                  )}
                  {task.internal && <ToneTag tone="info">{t('requests.task_internal')}</ToneTag>}
                  {task.needs_review && (
                    <ToneTag tone="warning">{t('requests.task_needs_review')}</ToneTag>
                  )}
                  {canEdit && hasPlanParts(task) && (
                    <Button
                      size="small"
                      type="link"
                      onClick={() => {
                        setOpen(open === task.id ? null : task.id);
                      }}
                      data-testid={`sr-task-parts-${String(task.position)}`}
                    >
                      {handover ? t('requests.task_handover') : t('requests.task_fields')}
                    </Button>
                  )}
                </Space>
                {open === task.id && (
                  <PlanTaskParts
                    task={task}
                    base="service-requests"
                    recordId={recordId}
                    onDone={() => {
                      setOpen(null);
                    }}
                  />
                )}
              </Flex>
            </List.Item>
          );
        }}
      />
    </Flex>
  );
}
