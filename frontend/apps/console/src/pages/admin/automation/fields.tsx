import { Button, Flex, Input, InputNumber, Select, Space, Typography } from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import type { ReactNode } from 'react';

import {
  useCustomFields,
  useIncidentCatalogue,
  useStructure,
  type RuleFieldOut,
} from '@supportx/api-client';
import { useAppearance, useLabel } from '@supportx/ui';

import { choiceName } from '../../customFields/values';
import { levelLabel, scaleLabel, statusLabel } from '../../incidents/labels';
import { CategoryPicker, UserPicker } from '../../incidents/pickers';
import { TagsInput } from '../../incidents/TagsInput';

import { LIST, NO_VALUE, OPERATORS, useFieldName, type Condition, type Conditions } from './rules';

/** The input for one value of one field: codes by their labels, references by their names. */
export function ValueInput({
  field,
  value,
  onChange,
  multiple = false,
  testId,
  ariaLabel,
}: {
  field: RuleFieldOut;
  value: unknown;
  onChange: (value: unknown) => void;
  multiple?: boolean;
  testId: string;
  ariaLabel: string;
}): ReactNode {
  const t = useLabel();
  const { locale } = useAppearance();
  const catalogue = useIncidentCatalogue();
  const custom = useCustomFields('incident');
  const groups = useStructure('groups', field.name === 'group_id');
  const sites = useStructure(
    'sites',
    field.name === 'site_id' || field.name === 'requester.site_id',
  );
  const departments = useStructure(
    'departments',
    field.name === 'department_id' || field.name === 'requester.department_id',
  );
  const codeLabel = (code: string): string => {
    switch (field.name) {
      case 'priority':
      case 'impact':
      case 'urgency':
        return scaleLabel(t, catalogue.data, field.name, code, locale);
      case 'status':
        return statusLabel(t, catalogue.data, code, locale);
      case 'level':
        return levelLabel(t, catalogue.data, code, locale);
      case 'channel':
        return t(`work_item_channel.${code}`);
      case 'status_category':
        return t(`status_category.${code}`);
      default: {
        const found = custom.data?.find((f) => `custom.${f.key}` === field.name);
        return found === undefined ? code : choiceName(t, found, code, locale);
      }
    }
  };
  const common = { 'data-testid': testId, 'aria-label': ariaLabel, style: { minWidth: 200 } };
  if (field.kind === 'code' || (field.kind === 'codes' && field.values !== null)) {
    return (
      <Select
        {...common}
        mode={multiple || field.kind === 'codes' ? 'multiple' : undefined}
        value={value as string | string[] | undefined}
        onChange={onChange}
        options={(field.values ?? []).map((code) => ({ value: code, label: codeLabel(code) }))}
      />
    );
  }
  if (field.kind === 'codes') {
    return (
      <TagsInput
        value={Array.isArray(value) ? (value as string[]) : []}
        onChange={onChange}
        testId={testId}
        ariaLabel={ariaLabel}
      />
    );
  }
  if (field.kind === 'boolean') {
    return (
      <Select
        {...common}
        value={value as boolean | undefined}
        onChange={onChange}
        options={[
          { value: true, label: t('history.yes') },
          { value: false, label: t('history.no') },
        ]}
      />
    );
  }
  if (field.kind === 'number') {
    return (
      <InputNumber
        {...common}
        value={typeof value === 'number' ? value : null}
        onChange={(next) => {
          onChange(next);
        }}
      />
    );
  }
  if (field.kind === 'reference') {
    const units =
      field.name === 'group_id'
        ? groups.data
        : field.name.endsWith('site_id')
          ? sites.data
          : field.name.endsWith('department_id')
            ? departments.data
            : undefined;
    if (units !== undefined) {
      return (
        <Select
          {...common}
          mode={multiple ? 'multiple' : undefined}
          showSearch
          optionFilterProp="label"
          value={value as string | string[] | undefined}
          onChange={onChange}
          options={units
            .filter((u) => !u.disabled || u.id === value)
            .map((u) => ({ value: u.id, label: u.name }))}
        />
      );
    }
    if (field.name === 'category_id') {
      return (
        <CategoryPicker
          value={(value as string | null) ?? null}
          onChange={onChange}
          testId={testId}
          ariaLabel={ariaLabel}
        />
      );
    }
    return (
      <UserPicker
        value={(value as string | null) ?? null}
        onChange={onChange}
        testId={testId}
        ariaLabel={ariaLabel}
      />
    );
  }
  return (
    <Input
      {...common}
      value={typeof value === 'string' ? value : ''}
      onChange={(event) => {
        onChange(event.target.value);
      }}
    />
  );
}

/** Conditions as rows: field, operator, value; joined by AND or OR (REQ-RUL-002). */
export function ConditionBuilder({
  fields,
  value,
  onChange,
  allowOp = () => true,
}: {
  fields: RuleFieldOut[];
  value: Conditions;
  onChange: (next: Conditions) => void;
  /** Narrows the operators offered (triggers: "changed from" for the status only). */
  allowOp?: (field: string, op: string) => boolean;
}) {
  const t = useLabel();
  const name = useFieldName();
  const byName = new Map(fields.map((f) => [f.name, f]));
  const update = (index: number, row: Condition) => {
    onChange({ ...value, rows: value.rows.map((r, i) => (i === index ? row : r)) });
  };
  return (
    <Space direction="vertical" style={{ width: '100%' }} data-testid="condition-builder">
      {value.rows.length === 0 ? (
        <Typography.Text type="secondary">{t('automation.conditions.none')}</Typography.Text>
      ) : (
        <Select
          aria-label={t('automation.conditions.join')}
          value={value.join}
          onChange={(join: 'and' | 'or') => {
            onChange({ ...value, join });
          }}
          options={[
            { value: 'and', label: t('automation.conditions.all') },
            { value: 'or', label: t('automation.conditions.any') },
          ]}
          style={{ width: 280 }}
          data-testid="condition-join"
        />
      )}
      {value.rows.map((row, index) => {
        const field = byName.get(row.field);
        const ops =
          field === undefined ? [] : OPERATORS[field.kind].filter((op) => allowOp(field.name, op));
        return (
          // Rows have no ID: they are edited in place, never reordered.
          <Flex key={index} gap={8} wrap align="center" data-testid={`condition-${String(index)}`}>
            <Select
              aria-label={t('automation.conditions.field')}
              showSearch
              optionFilterProp="label"
              value={row.field || undefined}
              placeholder={t('automation.conditions.field')}
              onChange={(next: string) => {
                update(index, { field: next, op: '', value: undefined });
              }}
              options={fields.map((f) => ({ value: f.name, label: name(f.name) }))}
              style={{ minWidth: 200 }}
              data-testid={`condition-${String(index)}-field`}
            />
            <Select
              aria-label={t('automation.conditions.op')}
              value={row.op || undefined}
              placeholder={t('automation.conditions.op')}
              disabled={field === undefined}
              onChange={(next: string) => {
                update(index, { ...row, op: next, value: LIST.has(next) ? [] : undefined });
              }}
              options={ops.map((op) => ({ value: op, label: t(`rule_op.${op}`) }))}
              style={{ minWidth: 160 }}
              data-testid={`condition-${String(index)}-op`}
            />
            {field !== undefined && row.op !== '' && !NO_VALUE.has(row.op) && (
              <ValueInput
                field={field}
                value={row.value}
                multiple={LIST.has(row.op)}
                onChange={(next) => {
                  update(index, { ...row, value: next });
                }}
                testId={`condition-${String(index)}-value`}
                ariaLabel={t('automation.conditions.value')}
              />
            )}
            <Button
              icon={<DeleteOutlined />}
              aria-label={t('automation.conditions.remove')}
              onClick={() => {
                onChange({ ...value, rows: value.rows.filter((_, i) => i !== index) });
              }}
            />
          </Flex>
        );
      })}
      <Button
        icon={<PlusOutlined />}
        onClick={() => {
          onChange({ ...value, rows: [...value.rows, { field: '', op: '' }] });
        }}
        data-testid="condition-add"
      >
        {t('automation.conditions.add')}
      </Button>
    </Space>
  );
}
