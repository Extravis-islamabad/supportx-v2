import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Flex, Form, Input, InputNumber, Radio, Select } from 'antd';

import { useRuleFields, useWorkflows } from '@supportx/api-client';
import { lengthLimit, useLabel } from '@supportx/ui';

import { fieldOptions, useFieldName } from '../automation/rules';
import type { FormProps } from './NodeForms';

// Settings forms for the structure and function steps (QA F-05, the coordinator's second
// group: split, join, sub-flow, function), and the retries every command step shares. Each
// edits the config exactly as the definition stores it; the server checks it on save.

type Config = Record<string, unknown>;

// The server's limits (domain/workflows.py).
const MIN_BRANCHES = 2;
const MAX_BRANCHES = 10;
const ID_MAX = 40;
const MAX_RETRIES = 5;
const RETRY_SECONDS_MIN = 10;
const RETRY_SECONDS_MAX = 24 * 3600;
const FUNCTION_TIMEOUT_MAX = 30;
const MAX_FUNCTION_IO = 20;
const FUNCTION_NAME_MAX = 60;
const JOIN_MODES = ['all', 'first', 'count'] as const;

function tree(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];

const whole = (value: unknown, fallback: number): number =>
  typeof value === 'number' && Number.isInteger(value) ? value : fallback;

/** A command step tried again when it fails: how often, and how long apart (REQ-WF-024). */
export function RetriesField({
  config,
  onChange,
  readOnly,
}: Omit<FormProps, 'recordType' | 'variables'>) {
  const t = useLabel();
  const retries = whole(config.retries, 0);
  return (
    <Flex gap={12} wrap>
      <Form.Item
        label={t('workflows.form.retries')}
        htmlFor="node-retries"
        extra={t('workflows.form.retries_help')}
        style={{ flex: '1 1 140px' }}
      >
        <InputNumber<number>
          id="node-retries"
          min={0}
          max={MAX_RETRIES}
          precision={0}
          value={retries}
          disabled={readOnly}
          onChange={(next) => {
            onChange({ ...config, retries: next ?? 0 });
          }}
          data-testid="node-retries"
        />
      </Form.Item>
      {retries > 0 && (
        <Form.Item
          label={t('workflows.form.retry_seconds')}
          htmlFor="node-retry-seconds"
          style={{ flex: '1 1 140px' }}
        >
          <InputNumber<number>
            id="node-retry-seconds"
            min={RETRY_SECONDS_MIN}
            max={RETRY_SECONDS_MAX}
            precision={0}
            value={whole(config.retry_seconds, 60)}
            disabled={readOnly}
            onChange={(next) => {
              onChange({ ...config, retry_seconds: next ?? 60 });
            }}
            data-testid="node-retry-seconds"
          />
        </Form.Item>
      )}
    </Flex>
  );
}

/** Branches that run side by side, each an output the admin names (REQ-WF-018). */
export function SplitForm({ config, onChange, readOnly }: FormProps) {
  const t = useLabel();
  const branches = strings(config.branches);
  const shown =
    branches.length >= MIN_BRANCHES ? branches : ['', ''].map((e, i) => branches[i] ?? e);
  const set = (next: string[]) => {
    onChange({ ...config, branches: next });
  };
  return (
    <>
      {shown.map((name, i) => {
        const n = i + 1;
        return (
          <Flex key={i} gap={8} align="start" data-testid={`split-branch-${String(n)}`}>
            <Form.Item
              label={t('workflows.form.branch', { n })}
              htmlFor={`split-branch-${String(n)}`}
              extra={i === 0 ? t('workflows.form.branch_help') : undefined}
              style={{ flex: 1, minWidth: 0, marginBottom: 8 }}
            >
              <Input
                id={`split-branch-${String(n)}`}
                value={name}
                disabled={readOnly}
                count={lengthLimit(ID_MAX)}
                onChange={(e) => {
                  set(shown.map((b, j) => (j === i ? e.target.value.trim() : b)));
                }}
                data-testid={`split-branch-${String(n)}-name`}
              />
            </Form.Item>
            {shown.length > MIN_BRANCHES && (
              <Button
                type="text"
                icon={<DeleteOutlined />}
                disabled={readOnly}
                aria-label={t('workflows.form.remove_branch', { n })}
                style={{ marginTop: 30 }}
                onClick={() => {
                  set(shown.filter((_, j) => j !== i));
                }}
                data-testid={`split-branch-${String(n)}-remove`}
              />
            )}
          </Flex>
        );
      })}
      <Form.Item>
        <Button
          icon={<PlusOutlined />}
          disabled={readOnly || shown.length >= MAX_BRANCHES}
          onClick={() => {
            set([...shown, '']);
          }}
          data-testid="split-add"
        >
          {t('workflows.form.add_branch')}
        </Button>
      </Form.Item>
    </>
  );
}

/** When the branches meet again, it goes on: all of them, the first, or a number of them. */
export function JoinForm({ config, onChange, readOnly }: FormProps) {
  const t = useLabel();
  const mode = typeof config.mode === 'string' ? config.mode : 'all';
  return (
    <>
      <Form.Item label={t('workflows.form.join_mode')}>
        <Radio.Group
          value={mode}
          disabled={readOnly}
          onChange={(e) => {
            const next = e.target.value as string;
            const rest = Object.fromEntries(Object.entries(config).filter(([k]) => k !== 'count'));
            onChange(
              next === 'count' ? { ...rest, mode: next, count: 2 } : { ...rest, mode: next },
            );
          }}
          options={JOIN_MODES.map((m) => ({ value: m, label: t(`workflow_join_mode.${m}`) }))}
          data-testid="join-mode"
        />
      </Form.Item>
      {mode === 'count' && (
        <Form.Item label={t('workflows.form.join_count')} htmlFor="join-count">
          <InputNumber<number>
            id="join-count"
            min={1}
            max={MAX_BRANCHES}
            precision={0}
            value={whole(config.count, 2)}
            disabled={readOnly}
            onChange={(next) => {
              onChange({ ...config, count: next ?? 1 });
            }}
            data-testid="join-count"
          />
        </Form.Item>
      )}
    </>
  );
}

/** Another workflow of the same record type, run as one step (REQ-WF-019). */
export function SubFlowForm({ config, onChange, recordType, readOnly }: FormProps) {
  const t = useLabel();
  const workflows = useWorkflows(recordType);
  return (
    <>
      <Form.Item
        label={t('workflows.form.sub_flow')}
        htmlFor="sub-flow"
        extra={t('workflows.form.sub_flow_help')}
      >
        <Select<string>
          id="sub-flow"
          showSearch
          optionFilterProp="label"
          value={typeof config.workflow_id === 'string' ? config.workflow_id : undefined}
          disabled={readOnly}
          onChange={(workflow_id) => {
            onChange({ ...config, workflow_id });
          }}
          options={(workflows.data ?? []).map((w) => ({ value: w.id, label: w.name }))}
          data-testid="sub-flow"
        />
      </Form.Item>
      <RetriesField config={config} onChange={onChange} readOnly={readOnly} />
    </>
  );
}

/**
 * A custom function, run outside the API (§6.7): its name, the record's fields it gets as
 * inputs, the variables its outputs fill, and how long it may run.
 */
export function FunctionForm({ config, onChange, recordType, variables, readOnly }: FormProps) {
  const t = useLabel();
  const fieldName = useFieldName();
  const fields = useRuleFields(recordType);
  const inputs = Object.entries(tree(config.inputs)).map(
    ([k, v]) => [k, typeof tree(v).field === 'string' ? (tree(v).field as string) : ''] as const,
  );
  const assign = Object.entries(tree(config.assign)).map(
    ([k, v]) => [k, typeof v === 'string' ? v : ''] as const,
  );
  const setInputs = (next: (readonly [string, string])[]) => {
    onChange({
      ...config,
      inputs: Object.fromEntries(next.map(([k, f]) => [k, { field: f }])),
    });
  };
  const setAssign = (next: (readonly [string, string])[]) => {
    onChange({ ...config, assign: Object.fromEntries(next) });
  };
  const variableOptions = variables
    .filter((v) => v.name !== '')
    .map((v) => ({ value: v.name, label: v.name }));
  return (
    <>
      <Form.Item
        label={t('workflows.form.function')}
        htmlFor="function-name"
        extra={t('workflows.form.function_help')}
      >
        <Input
          id="function-name"
          dir="ltr"
          value={typeof config.function === 'string' ? config.function : ''}
          disabled={readOnly}
          count={lengthLimit(FUNCTION_NAME_MAX)}
          onChange={(e) => {
            onChange({ ...config, function: e.target.value.trim() });
          }}
          data-testid="function-name"
        />
      </Form.Item>
      <Form.Item label={t('workflows.form.function_inputs')}>
        <Flex vertical gap={6}>
          {inputs.map(([name, field], i) => {
            const n = i + 1;
            return (
              <Flex key={i} gap={8} wrap data-testid={`function-input-${String(n)}`}>
                <Input
                  dir="ltr"
                  value={name}
                  disabled={readOnly}
                  aria-label={t('workflows.form.input_name', { n })}
                  placeholder={t('workflows.form.input_name_placeholder')}
                  style={{ flex: '1 1 120px', minWidth: 0 }}
                  onChange={(e) => {
                    setInputs(inputs.map((x, j) => (j === i ? [e.target.value.trim(), x[1]] : x)));
                  }}
                  data-testid={`function-input-${String(n)}-name`}
                />
                <Select<string>
                  value={field === '' ? undefined : field}
                  disabled={readOnly}
                  showSearch
                  optionFilterProp="label"
                  aria-label={t('workflows.form.input_field', { n })}
                  style={{ flex: '1 1 160px', minWidth: 0 }}
                  onChange={(next) => {
                    setInputs(inputs.map((x, j) => (j === i ? [x[0], next] : x)));
                  }}
                  options={fieldOptions(fields.data ?? [], fieldName)}
                  data-testid={`function-input-${String(n)}-field`}
                />
                <Button
                  type="text"
                  icon={<DeleteOutlined />}
                  disabled={readOnly}
                  aria-label={t('workflows.form.remove_input', { n })}
                  onClick={() => {
                    setInputs(inputs.filter((_, j) => j !== i));
                  }}
                  data-testid={`function-input-${String(n)}-remove`}
                />
              </Flex>
            );
          })}
          <div>
            <Button
              icon={<PlusOutlined />}
              disabled={readOnly || inputs.length >= MAX_FUNCTION_IO}
              onClick={() => {
                setInputs([...inputs, ['', '']]);
              }}
              data-testid="function-input-add"
            >
              {t('workflows.form.add_input')}
            </Button>
          </div>
        </Flex>
      </Form.Item>
      <Form.Item label={t('workflows.form.function_outputs')}>
        <Flex vertical gap={6}>
          {assign.map(([name, variable], i) => {
            const n = i + 1;
            return (
              <Flex key={i} gap={8} wrap data-testid={`function-output-${String(n)}`}>
                <Input
                  dir="ltr"
                  value={name}
                  disabled={readOnly}
                  aria-label={t('workflows.form.output_name', { n })}
                  placeholder={t('workflows.form.output_name_placeholder')}
                  style={{ flex: '1 1 120px', minWidth: 0 }}
                  onChange={(e) => {
                    setAssign(assign.map((x, j) => (j === i ? [e.target.value.trim(), x[1]] : x)));
                  }}
                  data-testid={`function-output-${String(n)}-name`}
                />
                <Select<string>
                  value={variable === '' ? undefined : variable}
                  disabled={readOnly}
                  aria-label={t('workflows.form.output_variable', { n })}
                  style={{ flex: '1 1 160px', minWidth: 0 }}
                  onChange={(next) => {
                    setAssign(assign.map((x, j) => (j === i ? [x[0], next] : x)));
                  }}
                  options={variableOptions}
                  data-testid={`function-output-${String(n)}-variable`}
                />
                <Button
                  type="text"
                  icon={<DeleteOutlined />}
                  disabled={readOnly}
                  aria-label={t('workflows.form.remove_output', { n })}
                  onClick={() => {
                    setAssign(assign.filter((_, j) => j !== i));
                  }}
                  data-testid={`function-output-${String(n)}-remove`}
                />
              </Flex>
            );
          })}
          <div>
            <Button
              icon={<PlusOutlined />}
              disabled={readOnly || assign.length >= MAX_FUNCTION_IO}
              onClick={() => {
                setAssign([...assign, ['', '']]);
              }}
              data-testid="function-output-add"
            >
              {t('workflows.form.add_output')}
            </Button>
          </div>
        </Flex>
      </Form.Item>
      <Form.Item label={t('workflows.form.function_timeout')} htmlFor="function-timeout">
        <InputNumber<number>
          id="function-timeout"
          min={1}
          max={FUNCTION_TIMEOUT_MAX}
          precision={0}
          value={whole(config.timeout_seconds, 10)}
          disabled={readOnly}
          onChange={(next) => {
            onChange({ ...config, timeout_seconds: next ?? 10 });
          }}
          data-testid="function-timeout"
        />
      </Form.Item>
      <RetriesField config={config} onChange={onChange} readOnly={readOnly} />
    </>
  );
}

export type { Config };
