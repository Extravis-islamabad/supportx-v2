import { Button, Drawer, Flex, Form, Input, InputNumber, Select } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useTaskChange,
  type IncidentTask,
  type IncidentTaskPatch,
  type PartsBase,
} from '@supportx/api-client';
import { DateTimeField, lengthLimit, reportError, useLabel } from '@supportx/ui';

type Draft = Pick<
  IncidentTaskPatch,
  | 'task_type'
  | 'scheduled_start'
  | 'scheduled_end'
  | 'actual_start'
  | 'actual_end'
  | 'estimated_minutes'
  | 'percent_complete'
  | 'remind_before_minutes'
> & { extra_cost: string | null; depends_on: string[] };

function draftOf(task: IncidentTask): Draft {
  return {
    task_type: task.task_type ?? null,
    scheduled_start: task.scheduled_start ?? null,
    scheduled_end: task.scheduled_end ?? null,
    actual_start: task.actual_start ?? null,
    actual_end: task.actual_end ?? null,
    estimated_minutes: task.estimated_minutes ?? null,
    percent_complete: task.percent_complete ?? null,
    remind_before_minutes: task.remind_before_minutes ?? null,
    extra_cost: task.extra_cost ?? null,
    depends_on: [...(task.depends_on ?? [])],
  };
}

/**
 * A task's details and what it waits for (WP-046a S1; REQ-INC-073, -075): type, scheduled and
 * actual times (an end before its start is refused by the server, its words shown by the field),
 * estimate, percent done, the reminder before the start, and the extra cost for those who may see
 * it. Dependencies are the same record's other tasks; a loop is refused with its reason.
 */
export function TaskDetails({
  task,
  siblings,
  base,
  recordId,
  money,
  onClose,
}: {
  task: IncidentTask;
  siblings: IncidentTask[];
  base: PartsBase;
  recordId: string;
  /** Whether the viewer may edit the record, and so see and set the extra cost. */
  money: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const change = useTaskChange(recordId, base);
  const [draft, setDraft] = useState<Draft>(() => draftOf(task));
  const [problems, setProblems] = useState<Record<string, string>>({});
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    setDraft((d) => ({ ...d, [key]: value }));
  };
  const showCost = money;
  const field = (name: string) =>
    problems[name] === undefined ? {} : { validateStatus: 'error' as const, help: problems[name] };
  const failed = (error: unknown) => {
    if (error instanceof ApiError && error.status === 422) {
      setProblems(
        Object.fromEntries(
          error.fieldErrors.map((f) => [
            f.field.replace(/^body\./, ''),
            t(f.message_key, f.params ?? {}),
          ]),
        ),
      );
      return;
    }
    reportError(error);
  };
  const save = () => {
    setProblems({});
    const { depends_on, extra_cost, ...details } = draft;
    change.mutate(
      {
        kind: 'update',
        taskId: task.id,
        version: task.version,
        task: { ...details, ...(showCost ? { extra_cost } : {}) },
      },
      {
        onSuccess: () => {
          const before = [...(task.depends_on ?? [])].sort().join();
          if ([...depends_on].sort().join() === before) {
            onClose();
            return;
          }
          change.mutate(
            { kind: 'dependencies', taskId: task.id, dependsOn: depends_on },
            { onSuccess: onClose, onError: failed },
          );
        },
        onError: failed,
      },
    );
  };
  return (
    <Drawer
      open
      title={t('incidents.tasks.details_title', { title: task.title })}
      width={520}
      onClose={onClose}
      destroyOnHidden
      data-testid="task-details"
      extra={
        <Flex gap={8}>
          <Button onClick={onClose}>{t('actions.cancel')}</Button>
          <Button
            type="primary"
            loading={change.isPending}
            onClick={save}
            data-testid="task-details-save"
          >
            {t('actions.save')}
          </Button>
        </Flex>
      }
    >
      <Form layout="vertical">
        <Form.Item label={t('task.field.task_type')} htmlFor="task-type" {...field('task_type')}>
          <Input
            id="task-type"
            value={draft.task_type ?? ''}
            count={lengthLimit(40)}
            onChange={(e) => {
              set('task_type', e.target.value === '' ? null : e.target.value);
            }}
            data-testid="task-details-type"
          />
        </Form.Item>
        <Flex gap={12} wrap>
          <Form.Item label={t('task.field.scheduled_start')} {...field('scheduled_start')}>
            <DateTimeField
              value={draft.scheduled_start ?? null}
              onChange={(v) => {
                set('scheduled_start', v);
              }}
              testId="task-details-scheduled-start"
            />
          </Form.Item>
          <Form.Item label={t('task.field.scheduled_end')} {...field('scheduled_end')}>
            <DateTimeField
              value={draft.scheduled_end ?? null}
              onChange={(v) => {
                set('scheduled_end', v);
              }}
              testId="task-details-scheduled-end"
            />
          </Form.Item>
        </Flex>
        <Flex gap={12} wrap>
          <Form.Item label={t('task.field.actual_start')} {...field('actual_start')}>
            <DateTimeField
              value={draft.actual_start ?? null}
              onChange={(v) => {
                set('actual_start', v);
              }}
              testId="task-details-actual-start"
            />
          </Form.Item>
          <Form.Item label={t('task.field.actual_end')} {...field('actual_end')}>
            <DateTimeField
              value={draft.actual_end ?? null}
              onChange={(v) => {
                set('actual_end', v);
              }}
              testId="task-details-actual-end"
            />
          </Form.Item>
        </Flex>
        <Flex gap={12} wrap>
          <Form.Item
            label={t('task.field.estimated_minutes')}
            htmlFor="task-estimate"
            {...field('estimated_minutes')}
          >
            <InputNumber
              id="task-estimate"
              min={0}
              max={525600}
              value={draft.estimated_minutes ?? null}
              onChange={(v) => {
                set('estimated_minutes', v);
              }}
            />
          </Form.Item>
          <Form.Item
            label={t('task.field.percent_complete')}
            htmlFor="task-percent"
            {...field('percent_complete')}
          >
            <InputNumber
              id="task-percent"
              min={0}
              max={100}
              value={draft.percent_complete ?? null}
              onChange={(v) => {
                set('percent_complete', v);
              }}
            />
          </Form.Item>
          <Form.Item
            label={t('task.field.remind_before_minutes')}
            htmlFor="task-reminder"
            {...field('remind_before_minutes')}
          >
            <InputNumber
              id="task-reminder"
              min={0}
              max={10080}
              value={draft.remind_before_minutes ?? null}
              onChange={(v) => {
                set('remind_before_minutes', v);
              }}
              data-testid="task-details-reminder"
            />
          </Form.Item>
          {showCost && (
            <Form.Item
              label={t('task.field.extra_cost')}
              htmlFor="task-cost"
              {...field('extra_cost')}
            >
              <InputNumber<string>
                id="task-cost"
                min="0"
                step="0.01"
                stringMode
                value={draft.extra_cost}
                onChange={(v) => {
                  set('extra_cost', v);
                }}
              />
            </Form.Item>
          )}
        </Flex>
        <Form.Item
          label={t('task.field.depends_on')}
          htmlFor="task-depends-on"
          extra={t('task.field.depends_on_help')}
          {...field('depends_on')}
        >
          <Select
            id="task-depends-on"
            mode="multiple"
            value={draft.depends_on}
            onChange={(v: string[]) => {
              set('depends_on', v);
            }}
            options={siblings
              .filter((s) => s.id !== task.id)
              .map((s) => ({ value: s.id, label: s.title }))}
            optionFilterProp="label"
            data-testid="task-details-depends-on"
          />
        </Form.Item>
      </Form>
    </Drawer>
  );
}
