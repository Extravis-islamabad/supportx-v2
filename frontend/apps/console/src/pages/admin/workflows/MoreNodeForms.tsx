import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import {
  Button,
  Flex,
  Form,
  Input,
  InputNumber,
  Radio,
  Select,
  Switch,
  Tag,
  Typography,
} from 'antd';
import { useState } from 'react';

import { useNodeTypes, useRuleFields, useUnits, useUser } from '@supportx/api-client';
import { DateTimeField, lengthLimit, useLabel } from '@supportx/ui';

import { ValueInput } from '../automation/fields';
import { fieldOptions, useFieldName } from '../automation/rules';
import { UserPicker } from '../../incidents/pickers';
import type { FormProps } from './NodeForms';
import { RetriesField } from './StructureForms';

// Settings forms for the steps that were JSON only (QA F-05, the coordinator's order: approval,
// field update, webhook, set variable). Each edits the config exactly as the definition stores
// it; the server checks it on save (domain/workflows.py) and its problems show on the step.

type Config = Record<string, unknown>;

// The server's limits (domain/workflows.py).
const MAX_APPROVERS = 50;
const WEBHOOK_URL_MAX = 2000;
const WEBHOOK_METHODS = ['POST', 'PUT', 'PATCH'] as const;
const MAX_WEBHOOK_HEADERS = 20;
const WEBHOOK_HEADER_MAX = 1000;
const MAX_WEBHOOK_FIELDS = 50;
const VARIABLE_TEXT_MAX = 2000;
const APPROVAL_RULES = ['any', 'all', 'majority'] as const;
// What the server shows for a stored header value (domain/workflows.py SECRET_MASK).
const SECRET_MASK = '•••';

function tree(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];

function Person({
  id,
  onRemove,
  disabled,
}: {
  id: string;
  onRemove: () => void;
  disabled: boolean;
}) {
  const t = useLabel();
  const user = useUser(id);
  const name = user.data?.display_name ?? '';
  return (
    <Tag
      closable={!disabled}
      onClose={(e) => {
        e.preventDefault();
        onRemove();
      }}
      closeIcon={<span aria-label={t('workflows.form.remove_person', { name })}>×</span>}
      data-testid={`approver-person-${id}`}
    >
      <bdi dir="auto">{name}</bdi>
    </Tag>
  );
}

/** Who decides (named people, groups, the record's roles) and how (REQ-WF-014). */
export function ApprovalForm({ config, onChange, recordType, readOnly }: FormProps) {
  const t = useLabel();
  const groups = useUnits('groups');
  const types = useNodeTypes(recordType);
  const roles = types.data?.find((n) => n.type === 'approval')?.roles ?? [];
  const approvers = tree(config.approvers);
  const users = strings(approvers.user_ids);
  const groupIds = strings(approvers.group_ids);
  const roleCodes = strings(approvers.roles);
  const full = users.length + groupIds.length + roleCodes.length >= MAX_APPROVERS;
  const setApprovers = (patch: Record<string, string[]>) => {
    onChange({
      ...config,
      approvers: { user_ids: users, group_ids: groupIds, roles: roleCodes, ...patch },
    });
  };
  return (
    <>
      <Form.Item label={t('workflows.form.approver_roles')} htmlFor="approval-roles">
        <Select<string[]>
          id="approval-roles"
          mode="multiple"
          allowClear
          optionFilterProp="label"
          value={roleCodes}
          disabled={readOnly}
          onChange={(next) => {
            setApprovers({ roles: next });
          }}
          options={roles.map((r) => ({ value: r, label: t(`work_item_role.${r}`) }))}
          data-testid="approval-roles"
        />
      </Form.Item>
      <Form.Item label={t('workflows.form.groups')} htmlFor="approval-groups">
        <Select<string[]>
          id="approval-groups"
          mode="multiple"
          allowClear
          optionFilterProp="label"
          value={groupIds}
          disabled={readOnly}
          onChange={(next) => {
            setApprovers({ group_ids: next });
          }}
          options={(groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))}
          data-testid="approval-groups"
        />
      </Form.Item>
      <Form.Item label={t('workflows.form.approver_people')}>
        <Flex vertical gap={6}>
          {users.length > 0 && (
            <Flex wrap gap={4}>
              {users.map((id) => (
                <Person
                  key={id}
                  id={id}
                  disabled={readOnly}
                  onRemove={() => {
                    setApprovers({ user_ids: users.filter((u) => u !== id) });
                  }}
                />
              ))}
            </Flex>
          )}
          <UserPicker
            value={null}
            disabled={readOnly || full}
            ariaLabel={t('workflows.form.add_person')}
            testId="approval-add-person"
            onChange={(id) => {
              if (id !== null && !users.includes(id)) setApprovers({ user_ids: [...users, id] });
            }}
          />
        </Flex>
      </Form.Item>
      <Form.Item label={t('workflows.form.approval_rule')}>
        <Radio.Group
          value={typeof config.rule === 'string' ? config.rule : 'any'}
          disabled={readOnly}
          onChange={(e) => {
            onChange({ ...config, rule: e.target.value as string });
          }}
          options={APPROVAL_RULES.map((r) => ({ value: r, label: t(`approval_rule.${r}`) }))}
          data-testid="approval-rule"
        />
      </Form.Item>
    </>
  );
}

/** The record's fields this step sets, each to a value (REQ-WF-015): rows of field and value. */
export function FieldUpdateForm({ config, onChange, recordType, readOnly }: FormProps) {
  const t = useLabel();
  const fieldName = useFieldName();
  const fields = useRuleFields(recordType);
  const settable = (fields.data ?? []).filter((f) => f.settable);
  const values = tree(config.values);
  const rows = Object.entries(values);
  const setValues = (next: [string, unknown][]) => {
    onChange({ ...config, values: Object.fromEntries(next) });
  };
  const free = settable.filter((f) => !(f.name in values));
  return (
    <>
      {rows.map(([name, value], i) => {
        const field = settable.find((f) => f.name === name);
        const n = i + 1;
        return (
          <Flex key={name} gap={8} align="start" wrap data-testid={`set-field-${String(n)}`}>
            <Select<string>
              value={name}
              disabled={readOnly}
              aria-label={t('workflows.form.set_field', { n })}
              style={{ flex: '1 1 160px', minWidth: 0 }}
              showSearch
              optionFilterProp="label"
              onChange={(next) => {
                setValues(rows.map(([k, v]) => (k === name ? [next, null] : [k, v])));
              }}
              options={fieldOptions(
                settable.filter((f) => f.name === name || !(f.name in values)),
                fieldName,
              )}
              data-testid={`set-field-${String(n)}-field`}
            />
            <div style={{ flex: '1 1 160px', minWidth: 0 }}>
              {field !== undefined && (
                <ValueInput
                  field={field}
                  value={value}
                  onChange={(next) => {
                    setValues(rows.map(([k, v]) => (k === name ? [k, next] : [k, v])));
                  }}
                  testId={`set-field-${String(n)}-value`}
                  ariaLabel={t('workflows.form.set_value', { field: fieldName(name) })}
                />
              )}
            </div>
            <Button
              type="text"
              icon={<DeleteOutlined />}
              disabled={readOnly}
              aria-label={t('workflows.form.remove_field', { field: fieldName(name) })}
              onClick={() => {
                setValues(rows.filter(([k]) => k !== name));
              }}
              data-testid={`set-field-${String(n)}-remove`}
            />
          </Flex>
        );
      })}
      <Form.Item>
        <Button
          icon={<PlusOutlined />}
          disabled={readOnly || free.length === 0}
          onClick={() => {
            const first = free[0];
            if (first !== undefined) setValues([...rows, [first.name, null]]);
          }}
          data-testid="set-field-add"
        >
          {t('workflows.form.add_field')}
        </Button>
      </Form.Item>
      <RetriesField config={config} onChange={onChange} readOnly={readOnly} />
    </>
  );
}

/** One outside call (REQ-WF-020): where, how, its own headers, the record's fields it carries. */
export function WebhookForm({ config, onChange, recordType, variables, readOnly }: FormProps) {
  const t = useLabel();
  const fieldName = useFieldName();
  const fields = useRuleFields(recordType);
  // Rows of their own: a row being typed may have no name yet, or the name of another row,
  // which the stored object cannot hold (lane B's #406 review). Rows with a name are saved.
  const [headers, setRows] = useState<[string, string][]>(() =>
    Object.entries(tree(config.headers)).map(([k, v]) => [k, typeof v === 'string' ? v : '']),
  );
  const setHeaders = (next: [string, string][]) => {
    setRows(next);
    onChange({ ...config, headers: Object.fromEntries(next.filter(([k]) => k !== '')) });
  };
  const twice = (name: string) => name !== '' && headers.filter(([k]) => k === name).length > 1;
  return (
    <>
      <Form.Item label={t('workflows.form.webhook_url')} htmlFor="webhook-url">
        <Input
          id="webhook-url"
          dir="ltr"
          inputMode="url"
          value={typeof config.url === 'string' ? config.url : ''}
          disabled={readOnly}
          placeholder={t('workflows.form.webhook_url_placeholder')}
          count={lengthLimit(WEBHOOK_URL_MAX)}
          onChange={(e) => {
            onChange({ ...config, url: e.target.value.trim() });
          }}
          data-testid="webhook-url"
        />
      </Form.Item>
      <Form.Item label={t('workflows.form.webhook_method')}>
        <Radio.Group
          value={typeof config.method === 'string' ? config.method : 'POST'}
          disabled={readOnly}
          onChange={(e) => {
            onChange({ ...config, method: e.target.value as string });
          }}
          options={WEBHOOK_METHODS.map((m) => ({ value: m, label: t(`webhook_method.${m}`) }))}
          data-testid="webhook-method"
        />
      </Form.Item>
      <Form.Item label={t('workflows.form.webhook_fields')} htmlFor="webhook-fields">
        <Select<string[]>
          id="webhook-fields"
          mode="multiple"
          allowClear
          optionFilterProp="label"
          maxCount={MAX_WEBHOOK_FIELDS}
          value={strings(config.fields)}
          disabled={readOnly}
          onChange={(next) => {
            onChange({ ...config, fields: next });
          }}
          options={fieldOptions(fields.data ?? [], fieldName)}
          data-testid="webhook-fields"
        />
      </Form.Item>
      <Form.Item label={t('workflows.form.webhook_headers')}>
        <Flex vertical gap={6}>
          {headers.map(([name, value], i) => {
            const n = i + 1;
            return (
              <Flex key={i} gap={8} wrap data-testid={`webhook-header-${String(n)}`}>
                <Input
                  dir="ltr"
                  value={name}
                  disabled={readOnly}
                  aria-label={t('workflows.form.header_name', { n })}
                  placeholder={t('workflows.form.header_name_placeholder')}
                  status={twice(name) ? 'error' : undefined}
                  style={{ flex: '1 1 120px', minWidth: 0 }}
                  onChange={(e) => {
                    setHeaders(
                      headers.map((h, j) => (j === i ? [e.target.value.trim(), h[1]] : h)),
                    );
                  }}
                  data-testid={`webhook-header-${String(n)}-name`}
                />
                {/* Write-only (the coordinator, #406): a saved value comes back masked and
                    stays as it is unless something new is typed here. */}
                <Input.Password
                  dir="ltr"
                  value={value === SECRET_MASK ? '' : value}
                  placeholder={
                    value === SECRET_MASK ? t('workflows.form.header_value_saved') : undefined
                  }
                  visibilityToggle={false}
                  autoComplete="new-password"
                  disabled={readOnly}
                  aria-label={t('workflows.form.header_value', { n })}
                  count={lengthLimit(WEBHOOK_HEADER_MAX)}
                  style={{ flex: '2 1 160px', minWidth: 0 }}
                  onChange={(e) => {
                    setHeaders(headers.map((h, j) => (j === i ? [h[0], e.target.value] : h)));
                  }}
                  data-testid={`webhook-header-${String(n)}-value`}
                />
                <Button
                  type="text"
                  icon={<DeleteOutlined />}
                  disabled={readOnly}
                  aria-label={t('workflows.form.remove_header', { n })}
                  onClick={() => {
                    setHeaders(headers.filter((_, j) => j !== i));
                  }}
                  data-testid={`webhook-header-${String(n)}-remove`}
                />
                {twice(name) && (
                  <Typography.Text type="danger" style={{ fontSize: 12, flexBasis: '100%' }}>
                    {t('workflows.form.header_twice')}
                  </Typography.Text>
                )}
              </Flex>
            );
          })}
          <div>
            <Button
              icon={<PlusOutlined />}
              disabled={readOnly || headers.length >= MAX_WEBHOOK_HEADERS}
              onClick={() => {
                setHeaders([...headers, ['', '']]);
              }}
              data-testid="webhook-header-add"
            >
              {t('workflows.form.add_header')}
            </Button>
          </div>
        </Flex>
      </Form.Item>
      <Form.Item
        label={t('workflows.form.webhook_keep_status')}
        htmlFor="webhook-status"
        extra={t('workflows.form.webhook_keep_status_help')}
      >
        <Select<string>
          id="webhook-status"
          allowClear
          value={typeof config.status_variable === 'string' ? config.status_variable : undefined}
          disabled={readOnly}
          onChange={(next: string | undefined) => {
            onChange({ ...config, status_variable: next ?? null });
          }}
          options={variables
            .filter((v) => v.kind === 'number' && v.name !== '')
            .map((v) => ({ value: v.name, label: v.name }))}
          data-testid="webhook-status"
        />
      </Form.Item>
      <RetriesField config={config} onChange={onChange} readOnly={readOnly} />
    </>
  );
}

/** A variable set to a fixed value, or to one of the record's fields. */
export function SetVariableForm({ config, onChange, recordType, variables, readOnly }: FormProps) {
  const t = useLabel();
  const fieldName = useFieldName();
  const fields = useRuleFields(recordType);
  const name = typeof config.variable === 'string' ? config.variable : undefined;
  const variable = variables.find((v) => v.name === name);
  const fromField = typeof config.from_field === 'string';
  const value = config.value;
  const fixed = () => {
    switch (variable?.kind) {
      case 'number':
        return (
          <InputNumber<number>
            id="variable-value"
            value={typeof value === 'number' ? value : null}
            disabled={readOnly}
            onChange={(next) => {
              onChange({ ...config, value: next });
            }}
            data-testid="variable-value"
          />
        );
      case 'boolean':
        return (
          <Switch
            id="variable-value"
            checked={value === true}
            disabled={readOnly}
            onChange={(next) => {
              onChange({ ...config, value: next });
            }}
            data-testid="variable-value"
          />
        );
      case 'datetime':
        return (
          <DateTimeField
            id="variable-value"
            value={typeof value === 'string' ? value : null}
            disabled={readOnly}
            onChange={(next) => {
              onChange({ ...config, value: next });
            }}
            testId="variable-value"
          />
        );
      default:
        return (
          <Input
            id="variable-value"
            value={typeof value === 'string' ? value : ''}
            disabled={readOnly}
            count={lengthLimit(VARIABLE_TEXT_MAX)}
            onChange={(e) => {
              onChange({ ...config, value: e.target.value });
            }}
            data-testid="variable-value"
          />
        );
    }
  };
  return (
    <>
      <Form.Item
        label={t('workflows.form.variable')}
        htmlFor="set-variable"
        extra={variables.length === 0 ? t('workflows.form.variable_none') : undefined}
      >
        <Select<string>
          id="set-variable"
          value={name}
          disabled={readOnly}
          onChange={(next) => {
            // A new variable may hold another kind: its value starts empty.
            onChange({ ...config, variable: next, value: null });
          }}
          options={variables
            .filter((v) => v.name !== '')
            .map((v) => ({ value: v.name, label: v.name }))}
          data-testid="set-variable"
        />
      </Form.Item>
      <Form.Item label={t('workflows.form.variable_from')}>
        <Radio.Group
          value={fromField ? 'field' : 'value'}
          disabled={readOnly}
          onChange={(e) => {
            const rest = Object.fromEntries(
              Object.entries(config).filter(([k]) => k !== 'from_field' && k !== 'value'),
            );
            onChange(
              e.target.value === 'field' ? { ...rest, from_field: '' } : { ...rest, value: null },
            );
          }}
          options={[
            { value: 'value', label: t('workflows.form.variable_from_value') },
            { value: 'field', label: t('workflows.form.variable_from_field') },
          ]}
          data-testid="variable-from"
        />
      </Form.Item>
      {fromField ? (
        <Form.Item label={t('workflows.form.variable_field')} htmlFor="variable-field">
          <Select<string>
            id="variable-field"
            showSearch
            optionFilterProp="label"
            value={config.from_field === '' ? undefined : (config.from_field as string)}
            disabled={readOnly}
            onChange={(next) => {
              onChange({ ...config, from_field: next });
            }}
            options={fieldOptions(fields.data ?? [], fieldName)}
            data-testid="variable-field"
          />
        </Form.Item>
      ) : (
        variable !== undefined && (
          <Form.Item label={t('workflows.form.variable_value')} htmlFor="variable-value">
            {fixed()}
          </Form.Item>
        )
      )}
    </>
  );
}

export type { Config };
