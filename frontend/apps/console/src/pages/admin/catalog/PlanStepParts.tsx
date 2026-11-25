import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Checkbox, Flex, Input, Select, Typography } from 'antd';

import type { CatalogItem, CatalogQuestion } from '@supportx/api-client';
import { textIn, useAppearance, useLabel } from '@supportx/ui';

import { UserPicker } from '../../incidents/pickers';
import { freshKey } from './planKeys';
import { PerLanguage } from './PerLanguage';
import { ConditionField } from './StagesEditor';

type Task = CatalogItem['plan'][number];
type TaskField = NonNullable<Task['fields']>[number];
type OwnerKind = NonNullable<Task['owner_kind']>;

const OWNER_KINDS: OwnerKind[] = ['person', 'requested_for_manager', 'person_answer'];
const FIELD_KINDS: TaskField['kind'][] = ['text', 'number', 'date', 'choice', 'person'];
const MAX_FIELDS = 10; // the server's MAX_TASK_FIELDS
const KEY = /^[a-z][a-z0-9_]{0,39}$/;

/**
 * A plan step's own parts (WP-047a S5): who it goes to (a person, the requested-for person's
 * manager, or the person a form answer names; REQ-SR-050), what it is (a task, or handing an
 * asset over; REQ-SR-056), the steps it waits for (REQ-SR-047), when it is made at all
 * (REQ-SR-048, Essentials) and the fields its owner fills in (REQ-SR-049). The server checks
 * the whole plan again on save (keys, loops, the fields' limits, the licence).
 */
export function PlanStepParts({
  tasks,
  index,
  questions,
  licensed,
  disabled,
  onChange,
}: {
  tasks: Task[];
  index: number;
  questions: CatalogQuestion[];
  licensed: boolean;
  disabled: boolean;
  onChange: (next: Task[]) => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const task = tasks[index];
  if (task === undefined) return null;
  const testId = `cat-task-${String(index)}`;
  const put = (next: Partial<Task>, all: Task[] = tasks) => {
    onChange(all.map((one, i) => (i === index ? { ...one, ...next } : one)));
  };
  // A step another waits for, and the step that waits, both need a key: given here, once.
  const keyed = (at: number, all: Task[]): [string, Task[]] => {
    const found = all[at]?.key;
    if (found != null && found !== '') return [found, all];
    const key = freshKey(all, at);
    return [key, all.map((one, i) => (i === at ? { ...one, key } : one))];
  };
  const others = tasks
    .map((other, at) => ({ other, at }))
    .filter(({ at }) => at !== index)
    .map(({ other, at }) => ({
      value: at,
      label: textIn(other.title, locale) || t('catalog_admin.plan.task_n', { n: at + 1 }),
      key: other.key,
    }));
  const waitsFor = (task.waits_for ?? [])
    .map((key) => others.find((o) => o.key === key)?.value)
    .filter((at): at is number => at !== undefined);
  const personQuestions = questions.filter((q) => q.kind === 'person');
  const fields = task.fields ?? [];
  const putField = (at: number, next: Partial<TaskField>) => {
    put({ fields: fields.map((f, i) => (i === at ? { ...f, ...next } : f)) });
  };
  return (
    <Flex vertical gap={12} data-testid={`${testId}-parts`}>
      <Flex gap={16} wrap align="center">
        <Select
          style={{ minWidth: 260 }}
          aria-label={t('catalog_admin.plan.owner_kind')}
          placeholder={t('catalog_admin.plan.owner_group')}
          allowClear
          disabled={disabled}
          value={task.owner_kind ?? (task.owner_id != null ? 'person' : undefined)}
          options={OWNER_KINDS.map((kind) => ({
            value: kind,
            label: t(`task_owner_kind.${kind}`),
            disabled: !licensed && kind !== 'person', // REQ-SR-050: Professional
          }))}
          onChange={(kind: OwnerKind | undefined) => {
            put({ owner_kind: kind ?? null, owner_id: null, question_key: null });
          }}
          data-testid={`${testId}-owner-kind`}
        />
        {(task.owner_kind ?? (task.owner_id != null ? 'person' : null)) === 'person' && (
          <UserPicker
            value={task.owner_id ?? null}
            onChange={(owner_id) => {
              put({ owner_kind: 'person', owner_id });
            }}
            testId={`${testId}-owner`}
            ariaLabel={t('task_owner_kind.person')}
          />
        )}
        {task.owner_kind === 'person_answer' && (
          <Select
            style={{ minWidth: 220 }}
            aria-label={t('catalog_admin.plan.owner_question')}
            placeholder={t('catalog_admin.plan.owner_question')}
            disabled={disabled}
            value={task.question_key ?? undefined}
            options={personQuestions.map((q) => ({
              value: q.key,
              label: textIn(q.label, locale) || q.key,
            }))}
            onChange={(question_key: string) => {
              put({ question_key });
            }}
            data-testid={`${testId}-owner-question`}
          />
        )}
        <Select
          style={{ minWidth: 200 }}
          aria-label={t('catalog_admin.plan.kind')}
          disabled={disabled}
          value={task.kind}
          options={(['task', 'asset_handover'] as const).map((kind) => ({
            value: kind,
            label: t(`plan_step_kind.${kind}`),
            disabled: !licensed && kind !== 'task', // REQ-SR-056: Professional
          }))}
          onChange={(kind: 'task' | 'asset_handover') => {
            put({ kind });
          }}
          data-testid={`${testId}-kind`}
        />
      </Flex>
      <Select
        mode="multiple"
        aria-label={t('catalog_admin.plan.waits_for')}
        placeholder={t('catalog_admin.plan.waits_for_none')}
        disabled={disabled || !licensed || others.length === 0}
        value={waitsFor}
        options={others.map(({ value, label }) => ({ value, label }))}
        onChange={(chosen: number[]) => {
          let all = tasks;
          const keys: string[] = [];
          for (const at of chosen) {
            const [key, next] = keyed(at, all);
            keys.push(key);
            all = next;
          }
          const [own, withOwn] = keys.length > 0 ? keyed(index, all) : [task.key, all];
          put({ waits_for: keys, key: own ?? null }, withOwn);
        }}
        data-testid={`${testId}-waits-for`}
      />
      <ConditionField
        condition={task.condition ?? null}
        questions={questions}
        licensed
        testId={`${testId}-condition`}
        onChange={(condition) => {
          const [own, all] = condition != null ? keyed(index, tasks) : [task.key, tasks];
          put({ condition, key: own ?? null }, all);
        }}
      />
      <Flex vertical gap={8} data-testid={`${testId}-fields`}>
        <Typography.Text strong>{t('catalog_admin.plan.fields')}</Typography.Text>
        {fields.length === 0 && (
          <Typography.Text type="secondary">{t('catalog_admin.plan.fields_none')}</Typography.Text>
        )}
        {fields.map((field, at) => (
          <Flex key={at} gap={8} wrap align="center" data-testid={`${testId}-field-${String(at)}`}>
            <Input
              style={{ width: 160 }}
              aria-label={t('catalog_admin.plan.field_key')}
              placeholder={t('catalog_admin.plan.field_key')}
              status={field.key !== '' && !KEY.test(field.key) ? 'error' : undefined}
              disabled={disabled}
              value={field.key}
              onChange={(event) => {
                putField(at, { key: event.target.value.trim().toLowerCase() });
              }}
            />
            <div style={{ flex: '1 1 260px' }}>
              <PerLanguage
                value={field.label}
                onChange={(label) => {
                  putField(at, { label });
                }}
                testId={`${testId}-field-${String(at)}-label`}
                limit={120}
              />
            </div>
            <Select
              style={{ width: 140 }}
              aria-label={t('catalog_admin.plan.field_kind')}
              disabled={disabled}
              value={field.kind}
              options={FIELD_KINDS.map((kind) => ({
                value: kind,
                label: t(`task_field_kind.${kind}`),
              }))}
              onChange={(kind: TaskField['kind']) => {
                putField(at, { kind });
              }}
            />
            {field.kind === 'choice' && (
              <Select
                mode="tags"
                style={{ minWidth: 200 }}
                aria-label={t('catalog_admin.plan.field_options')}
                placeholder={t('catalog_admin.plan.field_options')}
                disabled={disabled}
                value={field.options ?? []}
                onChange={(options: string[]) => {
                  putField(at, { options });
                }}
              />
            )}
            <Checkbox
              checked={field.required}
              disabled={disabled}
              onChange={(event) => {
                putField(at, { required: event.target.checked });
              }}
            >
              {t('catalog_admin.plan.required')}
            </Checkbox>
            <Button
              type="text"
              danger
              icon={<DeleteOutlined />}
              aria-label={t('catalog_admin.plan.field_remove')}
              disabled={disabled}
              onClick={() => {
                put({ fields: fields.filter((_, i) => i !== at) });
              }}
            />
          </Flex>
        ))}
        <Button
          icon={<PlusOutlined />}
          style={{ alignSelf: 'flex-start' }}
          disabled={disabled || !licensed || fields.length >= MAX_FIELDS}
          onClick={() => {
            put({
              fields: [
                ...fields,
                {
                  key: '',
                  label: {},
                  kind: 'text',
                  required: false,
                  options: [],
                  requester_visible: false,
                },
              ],
            });
          }}
          data-testid={`${testId}-field-add`}
        >
          {t('catalog_admin.plan.field_add')}
        </Button>
      </Flex>
    </Flex>
  );
}
