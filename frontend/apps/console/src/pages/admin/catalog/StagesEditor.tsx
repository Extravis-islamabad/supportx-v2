import { ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined } from '@ant-design/icons';
import { Alert, Card, Flex, Form, Input, Select, Switch, Typography } from 'antd';

import type { CatalogQuestion } from '@supportx/api-client';
import { useAppearance, useLabel, WriteButton } from '@supportx/ui';

import { GroupPicker, UserPicker } from '../../incidents/pickers';
import {
  type Approver,
  blankStage,
  type Kind,
  KINDS,
  MAX_APPROVERS,
  MAX_STAGES,
  type Op,
  OPS,
  type Rule,
  RULES,
  type Stage,
  TODAYS_KINDS,
  valueText,
} from './stages';

/** A single condition the editor can show and change; anything else is kept as it is. */
function simple(condition: Stage['condition']): { field: string; op: Op; value: unknown } | null {
  if (condition == null) return null;
  const { field, op, value } = condition as { field?: unknown; op?: unknown; value?: unknown };
  if (typeof field !== 'string' || !OPS.includes(op as Op)) return null;
  return { field, op: op as Op, value };
}

/**
 * An item's approval stages (WP-047a S2a; REQ-SR-029..032, Professional): in order, each with
 * its approvers, how they decide, whether it runs alongside the stage before it, when it
 * applies, its backup and whether a comment is required. Every choice is a labelled code; the
 * server checks the whole list again on save (the coordinator's condition 4: the same
 * validator as the form rules).
 */
export function StagesEditor({
  stages,
  questions,
  licensed = true,
  onChange,
}: {
  stages: Stage[];
  questions: CatalogQuestion[];
  /** `catalog` (REQ-SR-029..032): without it the item can only be reduced to one stage. */
  licensed?: boolean;
  onChange: (stages: Stage[]) => void;
}) {
  const t = useLabel();
  const put = (index: number, next: Partial<Stage>) => {
    onChange(stages.map((s, i) => (i === index ? { ...s, ...next } : s)));
  };
  // A stage runs alongside the one before it by sharing its parallel group (REQ-SR-030).
  const alongside = (index: number, on: boolean) => {
    const before = stages[index - 1];
    if (before === undefined) return;
    const group = before.parallel_group ?? `p${String(index)}`;
    const next = stages.map((s, i) => {
      if (i === index) return { ...s, parallel_group: on ? group : null };
      if (i === index - 1 && on) return { ...s, parallel_group: group };
      return s;
    });
    onChange(regrouped(next));
  };
  const move = (index: number, by: -1 | 1) => {
    const next = [...stages];
    const [taken] = next.splice(index, 1);
    if (taken === undefined) return;
    next.splice(index + by, 0, taken);
    onChange(regrouped(next));
  };
  return (
    <Flex vertical gap={12} data-testid="cat-stages">
      {!licensed && (
        <Alert
          type="warning"
          showIcon
          message={t('catalog_admin.approval.advanced_upgrade')}
          description={t('catalog_admin.stages.reduce_to_save')}
          data-testid="cat-stages-unlicensed"
        />
      )}
      {stages.map((stage, index) => (
        <StageCard
          key={index}
          index={index}
          count={stages.length}
          stage={stage}
          previous={stages[index - 1]}
          questions={questions}
          licensed={licensed}
          onChange={(next) => {
            put(index, next);
          }}
          onMove={(by) => {
            move(index, by);
          }}
          onAlongside={(on) => {
            alongside(index, on);
          }}
          onRemove={() => {
            onChange(regrouped(stages.filter((_, i) => i !== index)));
          }}
        />
      ))}
      <WriteButton
        style={{ alignSelf: 'flex-start' }}
        disabled={!licensed || stages.length >= MAX_STAGES}
        whyDisabled={
          licensed ? t('why.max_stages', { max: MAX_STAGES }) : t('why.professional_edition')
        }
        onClick={() => {
          onChange([...stages, blankStage()]);
        }}
        data-testid="cat-stage-add"
      >
        {t('catalog_admin.stages.add')}
      </WriteButton>
    </Flex>
  );
}

/**
 * Parallel groups are made by the editor, never typed: a stage that runs alongside the one
 * before it shares that stage's group. After a move or a removal, a group left with one stage
 * is dissolved, so the stored codes always describe neighbours.
 */
function regrouped(stages: Stage[]): Stage[] {
  return stages.map((s, i) => {
    const group = s.parallel_group ?? null;
    if (group === null) return s;
    const withPrev = stages[i - 1]?.parallel_group === group;
    const withNext = stages[i + 1]?.parallel_group === group;
    return withPrev || withNext ? s : { ...s, parallel_group: null };
  });
}

function StageCard({
  index,
  count,
  stage,
  previous,
  questions,
  licensed,
  onChange,
  onMove,
  onAlongside,
  onRemove,
}: {
  index: number;
  count: number;
  stage: Stage;
  previous: Stage | undefined;
  questions: CatalogQuestion[];
  licensed: boolean;
  onChange: (next: Partial<Stage>) => void;
  onMove: (by: -1 | 1) => void;
  onAlongside: (on: boolean) => void;
  onRemove: () => void;
}) {
  const t = useLabel();
  const approvers = stage.approvers;
  const alongside =
    previous !== undefined &&
    stage.parallel_group != null &&
    stage.parallel_group === previous.parallel_group;
  const n = index + 1;
  return (
    <Card
      size="small"
      data-testid={`cat-stage-${String(index)}`}
      title={t('requests.stage_n', { n })}
      extra={
        <Flex gap={4}>
          <WriteButton
            size="small"
            icon={<ArrowUpOutlined />}
            aria-label={t('catalog_admin.stages.move_up', { n })}
            disabled={index === 0}
            onClick={() => {
              onMove(-1);
            }}
          />
          <WriteButton
            size="small"
            icon={<ArrowDownOutlined />}
            aria-label={t('catalog_admin.stages.move_down', { n })}
            disabled={index === count - 1}
            onClick={() => {
              onMove(1);
            }}
          />
          <WriteButton
            size="small"
            danger
            icon={<DeleteOutlined />}
            aria-label={t('catalog_admin.stages.remove', { n })}
            disabled={count === 1}
            onClick={onRemove}
            data-testid={`cat-stage-remove-${String(index)}`}
          />
        </Flex>
      }
    >
      <Form layout="vertical" component="div">
        <Form.Item label={t('catalog_admin.approval.who')}>
          <Flex vertical gap={8}>
            {approvers.map((approver, i) => (
              <ApproverRow
                key={i}
                approver={approver}
                questions={questions}
                licensed={licensed}
                testId={`cat-stage-${String(index)}-approver-${String(i)}`}
                onChange={(next) => {
                  onChange({ approvers: approvers.map((a, j) => (j === i ? next : a)) });
                }}
                onRemove={() => {
                  onChange({ approvers: approvers.filter((_, j) => j !== i) });
                }}
              />
            ))}
            <WriteButton
              size="small"
              style={{ alignSelf: 'flex-start' }}
              disabled={approvers.length >= MAX_APPROVERS}
              whyDisabled={t('why.max_approvers', { max: MAX_APPROVERS })}
              onClick={() => {
                onChange({ approvers: [...approvers, { kind: 'person', person_id: null }] });
              }}
              data-testid={`cat-stage-${String(index)}-approver-add`}
            >
              {t('catalog_admin.stages.add_approver')}
            </WriteButton>
          </Flex>
        </Form.Item>
        <Flex gap={16} wrap>
          <Form.Item label={t('catalog_admin.stages.rule')} style={{ minWidth: 200 }}>
            <Select<Rule>
              value={stage.rule}
              options={RULES.map((r) => ({
                value: r,
                label: t(`approval_rule.${r}`),
                disabled: !licensed && r !== 'any', // REQ-SR-029: another rule is Professional
              }))}
              onChange={(rule) => {
                onChange({ rule });
              }}
              aria-label={t('catalog_admin.stages.rule')}
              data-testid={`cat-stage-${String(index)}-rule`}
            />
          </Form.Item>
          <Form.Item label={t('catalog_admin.approval.backup')} style={{ minWidth: 260 }}>
            <UserPicker
              value={stage.backup_id ?? null}
              onChange={(backup_id) => {
                onChange({ backup_id });
              }}
              testId={`cat-stage-${String(index)}-backup`}
              ariaLabel={t('catalog_admin.approval.backup')}
            />
          </Form.Item>
        </Flex>
        <Flex gap={24} wrap>
          {previous !== undefined && (
            <Toggle
              label={t('catalog_admin.stages.alongside_previous')}
              checked={alongside}
              testId={`cat-stage-${String(index)}-parallel`}
              onChange={onAlongside}
              disabled={!licensed && !alongside} // REQ-SR-030: turning it off stays allowed
            />
          )}
          <Toggle
            label={t('catalog_admin.approval.comments_required')}
            checked={stage.comments_required}
            onChange={(comments_required) => {
              onChange({ comments_required });
            }}
          />
        </Flex>
        <ConditionField
          condition={stage.condition ?? null}
          questions={questions}
          licensed={licensed}
          testId={`cat-stage-${String(index)}-condition`}
          onChange={(condition) => {
            onChange({ condition });
          }}
        />
      </Form>
    </Card>
  );
}

function ApproverRow({
  approver,
  questions,
  licensed,
  testId,
  onChange,
  onRemove,
}: {
  approver: Approver;
  questions: CatalogQuestion[];
  licensed: boolean;
  testId: string;
  onChange: (next: Approver) => void;
  onRemove: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const people = questions.filter((q) => q.kind === 'person');
  return (
    <Flex gap={8} wrap align="center" data-testid={testId}>
      <Select<Kind>
        style={{ minWidth: 260 }}
        value={approver.kind}
        options={KINDS.map((k) => ({
          value: k,
          label: t(`catalog_approver_kind.${k}`),
          disabled: !licensed && !TODAYS_KINDS.includes(k), // REQ-SR-031: Professional
        }))}
        onChange={(kind) => {
          onChange({ kind });
        }}
        aria-label={t('catalog_admin.stages.approver_kind')}
        data-testid={`${testId}-kind`}
      />
      {approver.kind === 'person' && (
        <UserPicker
          value={approver.person_id ?? null}
          onChange={(person_id) => {
            onChange({ kind: 'person', person_id });
          }}
          testId={`${testId}-person`}
          ariaLabel={t('catalog_approver_kind.person')}
        />
      )}
      {approver.kind === 'group' && (
        <GroupPicker
          value={approver.group_id ?? null}
          onChange={(group_id) => {
            onChange({ kind: 'group', group_id });
          }}
          testId={`${testId}-group`}
          ariaLabel={t('catalog_approver_kind.group')}
        />
      )}
      {approver.kind === 'person_answer' && (
        <Select<string>
          style={{ minWidth: 220 }}
          value={approver.question_key ?? undefined}
          placeholder={t('catalog_admin.stages.person_question')}
          notFoundContent={t('catalog_admin.stages.no_person_question')}
          options={people.map((q) => ({
            value: q.key,
            label: q.label[locale] ?? q.label.en ?? '',
          }))}
          onChange={(question_key) => {
            onChange({ kind: 'person_answer', question_key });
          }}
          aria-label={t('catalog_admin.stages.person_question')}
          data-testid={`${testId}-question`}
        />
      )}
      <WriteButton
        size="small"
        icon={<DeleteOutlined />}
        aria-label={t('catalog_admin.stages.remove_approver')}
        onClick={onRemove}
      />
    </Flex>
  );
}

/** "Applies only when": one question, an operator and a value (REQ-SR-032). */
function ConditionField({
  condition,
  questions,
  licensed,
  testId,
  onChange,
}: {
  condition: Stage['condition'];
  questions: CatalogQuestion[];
  licensed: boolean;
  testId: string;
  onChange: (next: Stage['condition']) => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const leaf = simple(condition);
  const fields = [
    { value: 'quantity', label: t('requests.condition_quantity') },
    ...questions.map((q) => ({ value: q.key, label: q.label[locale] ?? q.label.en ?? '' })),
  ];
  const question = questions.find((q) => q.key === leaf?.field);
  const options = (question?.options ?? []).map((code) => ({
    value: code,
    label: question?.option_labels?.[code]?.[locale] ?? question?.option_labels?.[code]?.en ?? code,
  }));
  const set = (next: { field: string; op: Op; value: unknown }) => {
    const needsValue = next.op !== 'is_null' && next.op !== 'is_not_null';
    onChange(
      needsValue
        ? { field: next.field, op: next.op, value: next.value }
        : { field: next.field, op: next.op },
    );
  };
  return (
    <Flex vertical gap={8} data-testid={testId}>
      <Toggle
        label={t('catalog_admin.stages.only_when')}
        checked={condition != null}
        disabled={!licensed && condition == null}
        testId={`${testId}-on`}
        onChange={(on) => {
          onChange(on ? { field: fields[0]?.value ?? 'quantity', op: 'eq', value: null } : null);
        }}
      />
      {condition != null && leaf === null && (
        <Typography.Text type="secondary">
          {t('catalog_admin.stages.combined_condition')}
        </Typography.Text>
      )}
      {leaf !== null && (
        <Flex gap={8} wrap>
          <Select<string>
            style={{ minWidth: 200 }}
            value={leaf.field}
            options={fields}
            onChange={(field) => {
              set({ ...leaf, field, value: null });
            }}
            aria-label={t('catalog_admin.stages.condition_field')}
            data-testid={`${testId}-field`}
          />
          <Select<Op>
            style={{ minWidth: 160 }}
            value={leaf.op}
            options={OPS.map((op) => ({ value: op, label: t(`rule_op.${op}`) }))}
            onChange={(op) => {
              set({ ...leaf, op, value: op === 'in' || op === 'not_in' ? [] : leaf.value });
            }}
            aria-label={t('catalog_admin.stages.condition_op')}
            data-testid={`${testId}-op`}
          />
          {leaf.op !== 'is_null' &&
            leaf.op !== 'is_not_null' &&
            (options.length > 0 ? (
              <Select<string | string[]>
                style={{ minWidth: 200 }}
                mode={leaf.op === 'in' || leaf.op === 'not_in' ? 'multiple' : undefined}
                value={(leaf.value as string | string[] | null) ?? undefined}
                options={options}
                onChange={(value) => {
                  set({ ...leaf, value });
                }}
                aria-label={t('catalog_admin.stages.condition_value')}
                data-testid={`${testId}-value`}
              />
            ) : (
              <Input
                style={{ width: 200 }}
                value={valueText(leaf.value)}
                onChange={(e) => {
                  const text = e.target.value;
                  const asNumber = leaf.field === 'quantity' && /^\d+$/.test(text);
                  set({ ...leaf, value: asNumber ? Number(text) : text });
                }}
                aria-label={t('catalog_admin.stages.condition_value')}
                data-testid={`${testId}-value`}
              />
            ))}
        </Flex>
      )}
    </Flex>
  );
}

function Toggle({
  label,
  checked,
  onChange,
  disabled,
  testId,
}: {
  label: string;
  checked: boolean;
  onChange: (on: boolean) => void;
  disabled?: boolean;
  testId?: string;
}) {
  return (
    <Flex align="center" gap={8}>
      <Switch
        checked={checked}
        onChange={onChange}
        disabled={disabled}
        aria-label={label}
        data-testid={testId}
      />
      <Typography.Text>{label}</Typography.Text>
    </Flex>
  );
}
