import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Checkbox, Flex, Form, Input, InputNumber, Radio, Select, Typography } from 'antd';
import { useState } from 'react';

import { useRuleFields, useUnits, type RuleFieldOut } from '@supportx/api-client';
import { TranslatedField, lengthLimit, useLabel, type TranslatedValue } from '@supportx/ui';

import { ConditionBuilder } from '../automation/fields';
import { fieldOptions, fromTree, toTree, useFieldName, type Conditions } from '../automation/rules';

// Settings forms for the node types people use most (WP-048b S4b). Each edits the node's
// config exactly as the definition stores it (ADR-043 §1) and the server checks it on save
// (domain/workflows.py); a type without a form keeps the "Advanced" editor.

type Config = Record<string, unknown>;

export interface FormProps {
  config: Config;
  onChange: (next: Config) => void;
  recordType: string;
  readOnly: boolean;
}

// The record's people a notice may name (the server's NOTICE_RELATIVES).
const RELATIVES = ['requester', 'on_behalf_of', 'assignee', 'group', 'group_head', 'followers'];
// What a wait can hear (the server's WaitEvent).
const WAIT_EVENTS = [
  'field_changed',
  'status_changed',
  'note_added',
  'requester_replied',
  'approval_decided',
  'task_completed',
  'worklog_added',
] as const;
// The status moves a workflow may run (work items' actions; system-only ones are refused on save).
const ACTIONS = [
  'start_work',
  'investigate',
  'confirm_root_cause',
  'await_fix',
  'analyse',
  'start_review',
  'hold',
  'wait_requester',
  'wait_third_party',
  'resume',
  'resolve',
  'close',
  'reopen',
  'cancel',
] as const;
const UNITS = [
  ['minutes', 60],
  ['hours', 3600],
  ['days', 86_400],
] as const;
type Unit = (typeof UNITS)[number][0];

function tree(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function texts(value: unknown): TranslatedValue {
  const found = tree(value) ?? {};
  return Object.fromEntries(
    Object.entries(found).filter((e): e is [string, string] => typeof e[1] === 'string'),
  );
}

/** The config without some keys (switching a timer from a duration to a date). */
function without(config: Config, ...keys: string[]): Config {
  return Object.fromEntries(Object.entries(config).filter(([k]) => !keys.includes(k)));
}

const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];

/**
 * A condition on the record's fields, as the shared rules grammar stores it. The rows are kept
 * here while they are being filled in: a new row has no field yet, which the stored form has
 * no place for (it would vanish on the way back).
 */
function ConditionField({
  fields,
  value,
  onChange,
}: {
  fields: RuleFieldOut[];
  value: unknown;
  onChange: (next: Record<string, unknown> | null) => void;
}) {
  const [rows, setRows] = useState<Conditions>(() => fromTree(tree(value)));
  return (
    <ConditionBuilder
      fields={fields}
      value={rows}
      onChange={(next) => {
        setRows(next);
        onChange(toTree(next));
      }}
    />
  );
}

/** A duration in seconds, typed as a number of minutes, hours or days. */
function DurationInput({
  id,
  seconds,
  onChange,
  disabled,
  testId,
}: {
  id: string;
  seconds: number | null;
  onChange: (next: number | null) => void;
  disabled: boolean;
  testId: string;
}) {
  const t = useLabel();
  const unit: Unit =
    seconds !== null && seconds % 86_400 === 0
      ? 'days'
      : seconds !== null && seconds % 3600 === 0
        ? 'hours'
        : 'minutes';
  const per = UNITS.find(([u]) => u === unit)?.[1] ?? 60;
  return (
    <Flex gap={8}>
      <InputNumber<number>
        id={id}
        min={1}
        precision={0}
        value={seconds === null ? null : Math.round(seconds / per)}
        disabled={disabled}
        onChange={(n) => {
          onChange(n === null ? null : n * per);
        }}
        data-testid={testId}
      />
      <Select<Unit>
        aria-label={t('workflows.form.unit')}
        value={unit}
        disabled={disabled || seconds === null}
        onChange={(next) => {
          const size = UNITS.find(([u]) => u === next)?.[1] ?? 60;
          if (seconds !== null) onChange(Math.max(1, Math.round(seconds / per)) * size);
        }}
        options={UNITS.map(([u]) => ({ value: u, label: t(`workflows.form.unit_${u}`) }))}
        style={{ minWidth: 110 }}
        data-testid={`${testId}-unit`}
      />
    </Flex>
  );
}

function BasisField({ config, onChange, readOnly }: Omit<FormProps, 'recordType'>) {
  const t = useLabel();
  return (
    <Form.Item label={t('workflows.form.basis')}>
      <Radio.Group
        value={config.basis ?? 'calendar'}
        disabled={readOnly}
        onChange={(e) => {
          onChange({ ...config, basis: e.target.value as string });
        }}
        options={['calendar', 'business'].map((b) => ({
          value: b,
          label: t(`workflows.form.basis_${b}`),
        }))}
      />
    </Form.Item>
  );
}

function IfForm({ config, onChange, recordType }: FormProps) {
  const t = useLabel();
  const fields = useRuleFields(recordType);
  return (
    <Form.Item label={t('workflows.form.condition')} help={t('workflows.form.if_help')}>
      <ConditionField
        fields={fields.data ?? []}
        value={config.condition}
        onChange={(condition) => {
          onChange({ ...config, condition });
        }}
      />
    </Form.Item>
  );
}

function SwitchForm({ config, onChange, recordType, readOnly }: FormProps) {
  const t = useLabel();
  const fields = useRuleFields(recordType);
  const cases = Array.isArray(config.cases)
    ? (config.cases as { port?: unknown; condition?: unknown }[])
    : [];
  const set = (next: typeof cases) => {
    onChange({ ...config, cases: next });
  };
  return (
    <Flex vertical gap={12}>
      <Typography.Text type="secondary">{t('workflows.form.switch_help')}</Typography.Text>
      {cases.map((c, i) => (
        <Flex
          key={i}
          vertical
          gap={8}
          style={{ borderInlineStart: '2px solid', borderColor: 'inherit', paddingInlineStart: 8 }}
          data-testid={`switch-case-${String(i)}`}
        >
          <Flex gap={8} align="center">
            <Input
              aria-label={t('workflows.form.case_name', { n: i + 1 })}
              placeholder={t('workflows.form.case_name', { n: i + 1 })}
              dir="ltr"
              value={typeof c.port === 'string' ? c.port : ''}
              disabled={readOnly}
              count={lengthLimit(40)}
              onChange={(e) => {
                set(cases.map((x, j) => (j === i ? { ...x, port: e.target.value } : x)));
              }}
              data-testid={`switch-case-${String(i)}-port`}
            />
            <Button
              icon={<DeleteOutlined />}
              disabled={readOnly}
              aria-label={t('workflows.form.remove_case', { n: i + 1 })}
              onClick={() => {
                set(cases.filter((_, j) => j !== i));
              }}
            />
          </Flex>
          <ConditionField
            fields={fields.data ?? []}
            value={c.condition}
            onChange={(condition) => {
              set(cases.map((x, j) => (j === i ? { ...x, condition } : x)));
            }}
          />
        </Flex>
      ))}
      <Button
        icon={<PlusOutlined />}
        disabled={readOnly || cases.length >= 20}
        onClick={() => {
          set([...cases, { port: `case_${String(cases.length + 1)}`, condition: null }]);
        }}
        data-testid="switch-add-case"
      >
        {t('workflows.form.add_case')}
      </Button>
    </Flex>
  );
}

function NotifyForm({ config, onChange, readOnly }: FormProps) {
  const t = useLabel();
  const groups = useUnits('groups');
  const audience = tree(config.audience) ?? {};
  const setAudience = (patch: Record<string, unknown>) => {
    onChange({ ...config, audience: { ...audience, ...patch } });
  };
  return (
    <>
      <Form.Item label={t('workflows.form.recipients')}>
        <Checkbox.Group
          value={strings(audience.relatives)}
          disabled={readOnly}
          onChange={(relatives) => {
            setAudience({ relatives });
          }}
          options={RELATIVES.map((r) => ({ value: r, label: t(`notification_recipient.${r}`) }))}
          data-testid="notify-relatives"
        />
      </Form.Item>
      <Form.Item label={t('workflows.form.groups')} htmlFor="notify-groups">
        <Select<string[]>
          id="notify-groups"
          mode="multiple"
          allowClear
          optionFilterProp="label"
          value={strings(audience.group_ids)}
          disabled={readOnly}
          onChange={(group_ids) => {
            setAudience({ group_ids });
          }}
          options={(groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))}
          data-testid="notify-groups"
        />
      </Form.Item>
      <TranslatedField
        label={t('workflows.form.subject')}
        value={texts(config.subject)}
        max={200}
        onChange={(subject) => {
          onChange({ ...config, subject });
        }}
        testId="notify-subject"
      />
      <TranslatedField
        label={t('workflows.form.message')}
        value={texts(config.body)}
        max={2000}
        onChange={(body) => {
          onChange({ ...config, body });
        }}
        testId="notify-body"
      />
    </>
  );
}

function TimerForm({ config, onChange, recordType, readOnly }: FormProps) {
  const t = useLabel();
  const fields = useRuleFields(recordType);
  const name = useFieldName();
  const dates = (fields.data ?? []).filter((f) => f.kind === 'datetime' && !f.derived);
  const byDate = typeof config.until_field === 'string';
  const seconds = typeof config.seconds === 'number' ? config.seconds : null;
  return (
    <>
      <Form.Item label={t('workflows.form.timer_kind')}>
        <Radio.Group
          value={byDate ? 'date' : 'duration'}
          disabled={readOnly}
          onChange={(e) => {
            const rest = without(config, 'seconds', 'until_field', 'offset_seconds');
            onChange(
              e.target.value === 'date'
                ? { ...rest, until_field: dates[0]?.name ?? '', offset_seconds: 0 }
                : { ...rest, seconds: 3600 },
            );
          }}
          options={[
            { value: 'duration', label: t('workflows.form.timer_duration') },
            { value: 'date', label: t('workflows.form.timer_date') },
          ]}
          data-testid="timer-kind"
        />
      </Form.Item>
      {byDate ? (
        <Form.Item label={t('workflows.form.date_field')} htmlFor="timer-field">
          <Select<string>
            id="timer-field"
            value={config.until_field as string}
            disabled={readOnly}
            onChange={(until_field) => {
              onChange({ ...config, until_field });
            }}
            options={fieldOptions(dates, name)}
            data-testid="timer-field"
          />
        </Form.Item>
      ) : (
        <Form.Item label={t('workflows.form.wait_for')} htmlFor="timer-seconds">
          <DurationInput
            id="timer-seconds"
            seconds={seconds}
            disabled={readOnly}
            onChange={(next) => {
              onChange({ ...config, seconds: next });
            }}
            testId="timer-seconds"
          />
        </Form.Item>
      )}
      <BasisField config={config} onChange={onChange} readOnly={readOnly} />
    </>
  );
}

function WaitForm({ config, onChange, recordType, readOnly }: FormProps) {
  const t = useLabel();
  const fields = useRuleFields(recordType);
  const limit = typeof config.limit_seconds === 'number' ? config.limit_seconds : null;
  return (
    <>
      <Form.Item label={t('workflows.form.wait_events')} htmlFor="wait-events">
        <Select<string[]>
          id="wait-events"
          mode="multiple"
          value={strings(config.events)}
          disabled={readOnly}
          onChange={(events) => {
            onChange({ ...config, events });
          }}
          options={WAIT_EVENTS.map((e) => ({ value: e, label: t(`workflow_wait_event.${e}`) }))}
          data-testid="wait-events"
        />
      </Form.Item>
      <Form.Item label={t('workflows.form.wait_until')} help={t('workflows.form.wait_until_help')}>
        <ConditionField
          fields={fields.data ?? []}
          value={config.condition}
          onChange={(condition) => {
            onChange({ ...config, condition });
          }}
        />
      </Form.Item>
      <Form.Item
        label={t('workflows.form.limit')}
        htmlFor="wait-limit"
        help={t('workflows.form.limit_help')}
      >
        <Flex gap={8} align="center" wrap>
          <Checkbox
            checked={limit !== null}
            disabled={readOnly}
            onChange={(e) => {
              const rest = without(config, 'limit_seconds');
              onChange(e.target.checked ? { ...rest, limit_seconds: 86_400 } : rest);
            }}
            data-testid="wait-has-limit"
          >
            {t('workflows.form.limit_on')}
          </Checkbox>
          {limit !== null && (
            <DurationInput
              id="wait-limit"
              seconds={limit}
              disabled={readOnly}
              onChange={(next) => {
                onChange({ ...config, limit_seconds: next });
              }}
              testId="wait-limit"
            />
          )}
        </Flex>
      </Form.Item>
      <BasisField config={config} onChange={onChange} readOnly={readOnly} />
    </>
  );
}

function SetStatusForm({ config, onChange, readOnly }: FormProps) {
  const t = useLabel();
  return (
    <Form.Item label={t('workflows.form.action')} htmlFor="status-action">
      <Select<string>
        id="status-action"
        value={typeof config.action === 'string' ? config.action : undefined}
        placeholder={t('workflows.form.action')}
        disabled={readOnly}
        onChange={(action) => {
          onChange({ ...config, action });
        }}
        options={ACTIONS.map((a) => ({ value: a, label: t(`work_item_action.${a}`) }))}
        data-testid="status-action"
      />
    </Form.Item>
  );
}

// The server's NOTE_MAX, MAX_NODE_TASKS and TASK_TITLE_MAX (domain/workflows.py).
const NOTE_MAX = 5000;
const MAX_TASKS = 20;
const TASK_TITLE_MAX = 200;
const MAX_DUE_DAYS = 365;

function NoteForm({ config, onChange, readOnly }: FormProps) {
  const t = useLabel();
  return (
    <>
      <TranslatedField
        label={t('workflows.form.note_text')}
        value={texts(config.text)}
        max={NOTE_MAX}
        onChange={(text) => {
          onChange({ ...config, text });
        }}
        testId="note-text"
      />
      <Form.Item>
        <Checkbox
          checked={config.private !== false}
          disabled={readOnly}
          onChange={(e) => {
            onChange({ ...config, private: e.target.checked });
          }}
          data-testid="note-private"
        >
          {t('workflows.form.note_private')}
        </Checkbox>
      </Form.Item>
    </>
  );
}

function TasksForm({ config, onChange, readOnly }: FormProps) {
  const t = useLabel();
  const groups = useUnits('groups');
  const titles = Array.isArray(config.titles) ? config.titles.map(texts) : [];
  const shown = titles.length === 0 ? [{}] : titles;
  const setTitles = (next: TranslatedValue[]) => {
    onChange({ ...config, titles: next });
  };
  return (
    <>
      {shown.map((title, i) => (
        <Flex key={i} gap={8} align="start">
          <div style={{ flex: 1, minWidth: 0 }}>
            <TranslatedField
              label={t('workflows.form.task_title', { n: i + 1 })}
              value={title}
              max={TASK_TITLE_MAX}
              onChange={(next) => {
                setTitles(shown.map((old, j) => (j === i ? next : old)));
              }}
              testId={`task-title-${String(i + 1)}`}
            />
          </div>
          {shown.length > 1 && (
            <Button
              type="text"
              icon={<DeleteOutlined />}
              disabled={readOnly}
              aria-label={t('workflows.form.remove_task', { n: i + 1 })}
              onClick={() => {
                setTitles(shown.filter((_, j) => j !== i));
              }}
              data-testid={`task-remove-${String(i + 1)}`}
            />
          )}
        </Flex>
      ))}
      <Form.Item>
        <Button
          icon={<PlusOutlined />}
          disabled={readOnly || shown.length >= MAX_TASKS}
          onClick={() => {
            setTitles([...shown, {}]);
          }}
          data-testid="task-add"
        >
          {t('workflows.form.add_task')}
        </Button>
      </Form.Item>
      <Form.Item label={t('workflows.form.task_group')} htmlFor="task-group">
        <Select<string>
          id="task-group"
          allowClear
          optionFilterProp="label"
          value={typeof config.owner_group_id === 'string' ? config.owner_group_id : undefined}
          disabled={readOnly}
          onChange={(owner_group_id: string | undefined) => {
            onChange({ ...config, owner_group_id: owner_group_id ?? null });
          }}
          options={(groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))}
          data-testid="task-group"
        />
      </Form.Item>
      <Form.Item
        label={t('workflows.form.task_due')}
        htmlFor="task-due"
        extra={t('workflows.form.task_due_help')}
      >
        <InputNumber<number>
          id="task-due"
          min={0}
          max={MAX_DUE_DAYS}
          precision={0}
          value={typeof config.due_days === 'number' ? config.due_days : null}
          disabled={readOnly}
          onChange={(due_days) => {
            onChange({ ...config, due_days });
          }}
          data-testid="task-due"
        />
      </Form.Item>
    </>
  );
}

const FORMS: Record<string, (props: FormProps) => React.JSX.Element> = {
  if: IfForm,
  switch: SwitchForm,
  notify: NotifyForm,
  timer: TimerForm,
  wait: WaitForm,
  set_status: SetStatusForm,
  note: NoteForm,
  tasks: TasksForm,
};

/** The node type's form, or null when it has none (the "Advanced" editor is its form). */
export function NodeForm({ type, ...props }: FormProps & { type: string }) {
  const Shown = FORMS[type];
  return Shown === undefined ? null : (
    <Form layout="vertical" data-testid={`node-form-${type}`}>
      <Shown {...props} />
    </Form>
  );
}
