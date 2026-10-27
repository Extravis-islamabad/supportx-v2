import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Input, InputNumber, Segmented, Select, Space, Typography } from 'antd';

import { useLabels } from '@supportx/labels';
import { DateField, DateTimeField, DateTimeRangeField, lengthLimit } from '@supportx/ui';

import {
  emptyValue,
  needsValue,
  newRow,
  OPERATORS,
  rowProblems,
  type FilterFieldOption,
  type FilterModel,
  type FilterOp,
  type FilterRow,
  type FilterValue,
} from './model';

export interface FilterBuilderProps {
  /** The fields the API allows here, labelled by the caller. */
  fields: FilterFieldOption[];
  value: FilterModel;
  onChange: (value: FilterModel) => void;
  testId?: string;
}

/**
 * Conditions joined by "all" or "any", with operators that fit each field's type
 * (REQ-RPT-029). A row with a field but no value shows an inline error; callers disable their
 * run or save action while `rowProblems(value)` is not empty, and say why.
 */
export function FilterBuilder({ fields, value, onChange, testId = 'filter' }: FilterBuilderProps) {
  const t = useLabels();
  const problems = rowProblems(value);
  const byName = new Map(fields.map((f) => [f.name, f]));
  const set = (index: number, row: FilterRow) => {
    onChange({ ...value, rows: value.rows.map((r, i) => (i === index ? row : r)) });
  };
  const first = fields[0];

  return (
    <Space direction="vertical" style={{ width: '100%' }} data-testid={testId}>
      {value.rows.length > 1 && (
        <Segmented
          aria-label={t('filter.join')}
          value={value.join}
          onChange={(join) => {
            onChange({ ...value, join: join as 'and' | 'or' });
          }}
          options={[
            { value: 'and', label: t('filter.match_all') },
            { value: 'or', label: t('filter.match_any') },
          ]}
          data-testid={`${testId}-join`}
        />
      )}
      {value.rows.length === 0 && (
        <Typography.Text type="secondary">{t('filter.none')}</Typography.Text>
      )}
      {value.rows.map((row, index) => {
        const field = byName.get(row.field);
        const problem = problems.get(index);
        return (
          <div key={index} data-testid={`${testId}-row-${String(index)}`}>
            <Space wrap align="start">
              <Select
                aria-label={t('filter.field')}
                style={{ minWidth: 180 }}
                showSearch
                optionFilterProp="label"
                value={row.field}
                options={fields.map((f) => ({ value: f.name, label: f.label }))}
                onChange={(name: string) => {
                  const next = byName.get(name);
                  if (next !== undefined) set(index, newRow(next));
                }}
                data-testid={`${testId}-field-${String(index)}`}
              />
              <Select
                aria-label={t('filter.operator')}
                style={{ minWidth: 160 }}
                value={row.op}
                options={(field ? OPERATORS[field.type] : [row.op]).map((op) => ({
                  value: op,
                  label: t(`filter_op.${op}`),
                }))}
                onChange={(op: FilterOp) => {
                  set(index, { ...row, op, value: emptyValue(op) });
                }}
                data-testid={`${testId}-op-${String(index)}`}
              />
              {field && needsValue(row.op) && (
                <ValueEditor
                  field={field}
                  row={row}
                  onChange={(next) => {
                    set(index, { ...row, value: next });
                  }}
                  testId={`${testId}-value-${String(index)}`}
                  invalid={problem !== undefined}
                />
              )}
              <Button
                aria-label={t('filter.remove')}
                icon={<DeleteOutlined />}
                onClick={() => {
                  onChange({ ...value, rows: value.rows.filter((_, i) => i !== index) });
                }}
                data-testid={`${testId}-remove-${String(index)}`}
              />
            </Space>
            {problem && (
              <Typography.Text type="danger" role="alert" style={{ display: 'block' }}>
                {t(`filter.${problem}`)}
              </Typography.Text>
            )}
          </div>
        );
      })}
      {first && (
        <Button
          icon={<PlusOutlined />}
          onClick={() => {
            onChange({ ...value, rows: [...value.rows, newRow(first)] });
          }}
          data-testid={`${testId}-add`}
        >
          {t('filter.add')}
        </Button>
      )}
    </Space>
  );
}

function ValueEditor({
  field,
  row,
  onChange,
  testId,
  invalid,
}: {
  field: FilterFieldOption;
  row: FilterRow;
  onChange: (value: FilterValue) => void;
  testId: string;
  invalid: boolean;
}) {
  const t = useLabels();
  const status = invalid ? 'error' : undefined;
  const label = t('filter.value');
  if (row.op === 'last_n_days' || row.op === 'next_n_days') {
    return (
      <Space>
        <InputNumber
          aria-label={t('filter.days')}
          min={1}
          max={3650}
          status={status}
          value={typeof row.value === 'number' ? row.value : null}
          onChange={(days) => {
            onChange(days);
          }}
          data-testid={testId}
        />
        <Typography.Text>{t('filter.days')}</Typography.Text>
      </Space>
    );
  }
  if (row.op === 'in' || row.op === 'not_in') {
    const values = Array.isArray(row.value) ? (row.value as string[]) : [];
    return (
      <Select
        mode={field.choices ? 'multiple' : 'tags'}
        aria-label={label}
        style={{ minWidth: 220 }}
        status={status}
        showSearch
        optionFilterProp="label"
        value={values}
        options={field.choices?.map((c) => ({ value: c.value, label: c.label }))}
        onChange={(next: string[]) => {
          onChange(next);
        }}
        data-testid={testId}
      />
    );
  }
  if (field.type === 'datetime' && row.op === 'between') {
    const range = Array.isArray(row.value)
      ? (row.value as [string | null, string | null])
      : ([null, null] as [string | null, string | null]);
    return <DateTimeRangeField value={range} onChange={onChange} testId={testId} />;
  }
  if (field.type === 'datetime') {
    return (
      <DateTimeField
        value={typeof row.value === 'string' ? row.value : null}
        onChange={onChange}
        testId={testId}
      />
    );
  }
  if (field.type === 'date') {
    return (
      <DateField
        ariaLabel={label}
        value={typeof row.value === 'string' ? row.value : null}
        onChange={onChange}
        testId={testId}
      />
    );
  }
  if (field.type === 'boolean') {
    return (
      <Select
        aria-label={label}
        style={{ minWidth: 120 }}
        status={status}
        value={typeof row.value === 'boolean' ? String(row.value) : undefined}
        options={[
          { value: 'true', label: t('filter.yes') },
          { value: 'false', label: t('filter.no') },
        ]}
        onChange={(next: string) => {
          onChange(next === 'true');
        }}
        data-testid={testId}
      />
    );
  }
  if (field.type === 'integer' || field.type === 'decimal') {
    if (row.op === 'between') {
      const pair = Array.isArray(row.value)
        ? (row.value as [string | null, string | null])
        : [null, null];
      const at = (i: 0 | 1) => (pair[i] === null || pair[i] === '' ? null : Number(pair[i]));
      return (
        <Space>
          <InputNumber
            aria-label={t('filter.from')}
            status={status}
            value={at(0)}
            onChange={(n) => {
              onChange([n === null ? null : String(n), pair[1] ?? null]);
            }}
            data-testid={`${testId}-from`}
          />
          <InputNumber
            aria-label={t('filter.to')}
            status={status}
            value={at(1)}
            onChange={(n) => {
              onChange([pair[0] ?? null, n === null ? null : String(n)]);
            }}
            data-testid={`${testId}-to`}
          />
        </Space>
      );
    }
    return (
      <InputNumber
        aria-label={label}
        status={status}
        value={typeof row.value === 'number' ? row.value : null}
        onChange={(n) => {
          onChange(n);
        }}
        data-testid={testId}
      />
    );
  }
  return (
    <Input
      aria-label={label}
      style={{ width: 220 }}
      status={status}
      count={lengthLimit(200)}
      value={typeof row.value === 'string' ? row.value : ''}
      onChange={(event) => {
        onChange(event.target.value);
      }}
      data-testid={testId}
    />
  );
}
