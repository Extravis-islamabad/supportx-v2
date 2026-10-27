import { Checkbox, Form, Input, InputNumber, Radio, Select, Space, Typography } from 'antd';
import type { ReactNode } from 'react';

import type { CustomField, IncidentPerson } from '@supportx/api-client';
import {
  Controller,
  parseFieldMessage,
  type Control,
  type FieldValues,
  type Path,
} from '@supportx/forms';
import { DateField, DateTimeField, useAppearance, useLabel, lengthLimit } from '@supportx/ui';

import { UserPicker } from '../incidents/pickers';
import {
  choiceName,
  fieldName,
  LONG_TEXT_MAX,
  localized,
  safeUrl,
  TEXT_MAX,
  useCustomValueText,
} from './values';

/**
 * Custom fields on screen (WP-026, REQ-INC-014): one control and one read-only view per field
 * type, used by the create form, the record's properties, the template editor and the admin
 * screen (default value). A field is always shown by its label in the user's language, else
 * English, never by its key (AC3).
 */

/** A custom value read-only: links for web and mail addresses, text for the rest. */
export function CustomFieldValue({
  field,
  value,
  people,
}: {
  field: CustomField;
  value: unknown;
  people?: Record<string, Pick<IncidentPerson, 'display_name'>>;
}) {
  const text = useCustomValueText()(field, value, people);
  if (text === '') return null;
  if (field.field_type === 'url') {
    const href = safeUrl(text);
    return href === null ? (
      <bdi dir="auto">{text}</bdi>
    ) : (
      <Typography.Link href={href} target="_blank" rel="noopener noreferrer">
        <bdi dir="ltr">{text}</bdi>
      </Typography.Link>
    );
  }
  if (field.field_type === 'email') {
    return (
      <Typography.Link href={`mailto:${text}`}>
        <bdi dir="ltr">{text}</bdi>
      </Typography.Link>
    );
  }
  if (field.field_type === 'long_text') {
    return (
      <bdi dir="auto" style={{ whiteSpace: 'pre-wrap' }}>
        {text}
      </bdi>
    );
  }
  return <bdi dir="auto">{text}</bdi>;
}

export interface CustomFieldControlProps {
  field: CustomField;
  value: unknown;
  onChange: (value: unknown) => void;
  id?: string;
  testId: string;
  ariaLabel: string;
  /** A person already chosen (shown when not in the loaded page of people). */
  current?: { id: string; name: string; email: string } | null;
  /** The value saved on the record: a retired choice stays selectable there only. */
  saved?: unknown;
  autoFocus?: boolean;
}

/** The control for one custom field's value, by type. Empty values are `null`. */
export function CustomFieldControl({
  field,
  value,
  onChange,
  id,
  testId,
  ariaLabel,
  current,
  saved,
  autoFocus,
}: CustomFieldControlProps): ReactNode {
  const t = useLabel();
  const { locale } = useAppearance();
  const rules = field.validation;
  const kept = new Set<string>(
    Array.isArray(saved) ? (saved as string[]) : typeof saved === 'string' ? [saved] : [],
  );
  const options = field.choices
    .filter((c) => !c.retired || (c.code !== null && kept.has(c.code ?? '')))
    .map((c) => ({ value: c.code ?? '', label: choiceName(t, field, c.code ?? '', locale) }));
  const text = (next: string) => {
    onChange(next === '' ? null : next);
  };
  switch (field.field_type) {
    case 'text':
    case 'email':
    case 'phone':
    case 'url':
      return (
        <Input
          id={id}
          aria-label={ariaLabel}
          autoFocus={autoFocus}
          dir={field.field_type === 'text' ? 'auto' : 'ltr'}
          type={
            field.field_type === 'email' ? 'email' : field.field_type === 'url' ? 'url' : 'text'
          }
          inputMode={field.field_type === 'phone' ? 'tel' : undefined}
          count={lengthLimit(rules.max_length ?? TEXT_MAX)}
          value={typeof value === 'string' ? value : ''}
          onChange={(event) => {
            text(event.target.value);
          }}
          data-testid={testId}
        />
      );
    case 'long_text':
      return (
        <Input.TextArea
          id={id}
          aria-label={ariaLabel}
          autoFocus={autoFocus}
          dir="auto"
          autoSize={{ minRows: 2, maxRows: 8 }}
          count={lengthLimit(rules.max_length ?? LONG_TEXT_MAX, true)}
          value={typeof value === 'string' ? value : ''}
          onChange={(event) => {
            text(event.target.value);
          }}
          data-testid={testId}
        />
      );
    case 'integer':
    case 'decimal':
    case 'currency':
      return (
        // No min, max or precision: those would change the typed number without a word; the
        // limits are refused with a message at the field instead (QA BUG-03).
        <InputNumber<string>
          id={id}
          aria-label={ariaLabel}
          autoFocus={autoFocus}
          stringMode
          suffix={field.field_type === 'currency' ? field.currency : undefined}
          value={typeof value === 'number' || typeof value === 'string' ? String(value) : null}
          onChange={(next) => {
            onChange(next === null || next === '' ? null : next);
          }}
          style={{ width: '100%', maxWidth: 260 }}
          data-testid={testId}
        />
      );
    case 'date':
      return (
        <DateField
          id={id}
          ariaLabel={ariaLabel}
          value={typeof value === 'string' ? value : null}
          onChange={onChange}
          testId={testId}
        />
      );
    case 'datetime':
      return (
        <DateTimeField
          id={id}
          value={typeof value === 'string' ? value : null}
          onChange={onChange}
          testId={testId}
        />
      );
    case 'yes_no':
      return (
        <Radio.Group
          id={id}
          aria-label={ariaLabel}
          value={value === true ? 'yes' : value === false ? 'no' : undefined}
          onChange={(event) => {
            onChange(event.target.value === 'yes');
          }}
          data-testid={testId}
        >
          <Radio value="yes">{t('custom_fields.yes')}</Radio>
          <Radio value="no">{t('custom_fields.no')}</Radio>
          {value !== null && value !== undefined && (
            <Typography.Link
              onClick={() => {
                onChange(null);
              }}
              data-testid={`${testId}-clear`}
            >
              {t('custom_fields.clear')}
            </Typography.Link>
          )}
        </Radio.Group>
      );
    case 'choice':
      if (field.display === 'radio') {
        return (
          <Space direction="vertical" size={4}>
            <Radio.Group
              id={id}
              aria-label={ariaLabel}
              value={typeof value === 'string' ? value : undefined}
              onChange={(event) => {
                onChange(event.target.value as string);
              }}
              options={options}
              data-testid={testId}
            />
            {typeof value === 'string' && (
              <Typography.Link
                onClick={() => {
                  onChange(null);
                }}
                data-testid={`${testId}-clear`}
              >
                {t('custom_fields.clear')}
              </Typography.Link>
            )}
          </Space>
        );
      }
      return (
        <Select
          id={id}
          aria-label={ariaLabel}
          autoFocus={autoFocus}
          allowClear
          showSearch
          optionFilterProp="label"
          value={typeof value === 'string' ? value : undefined}
          onChange={(next: string | undefined) => {
            onChange(next ?? null);
          }}
          options={options}
          style={{ width: '100%' }}
          data-testid={testId}
        />
      );
    case 'multi_choice':
      if (field.display === 'radio') {
        return (
          <div id={id} role="group" aria-label={ariaLabel}>
            <Checkbox.Group
              value={Array.isArray(value) ? (value as string[]) : []}
              onChange={(next) => {
                onChange(next.length === 0 ? null : next);
              }}
              options={options}
              data-testid={testId}
            />
          </div>
        );
      }
      return (
        <Select
          id={id}
          mode="multiple"
          aria-label={ariaLabel}
          autoFocus={autoFocus}
          allowClear
          optionFilterProp="label"
          value={Array.isArray(value) ? (value as string[]) : []}
          onChange={(next: string[]) => {
            onChange(next.length === 0 ? null : next);
          }}
          options={options}
          style={{ width: '100%' }}
          data-testid={testId}
        />
      );
    case 'person':
      return (
        <UserPicker
          id={id}
          value={typeof value === 'string' ? value : null}
          current={current ?? null}
          onChange={onChange}
          testId={testId}
          ariaLabel={ariaLabel}
        />
      );
  }
}

/**
 * One custom field in a React Hook Form form, as `custom.<key>`: its label and help in the
 * user's language, the control for its type and its error (client or server) underneath.
 */
export function CustomFormField<T extends FieldValues>({
  control,
  field,
  required,
}: {
  control: Control<T>;
  field: CustomField;
  required: boolean;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const name = `custom.${field.key}` as Path<T>;
  const id = `field-custom-${field.key}`;
  const label = fieldName(field, locale);
  const help = localized(field.help, locale);
  return (
    <Controller
      control={control}
      name={name}
      render={({ field: input, fieldState }) => {
        const message = parseFieldMessage(fieldState.error?.message);
        return (
          <Form.Item
            label={<bdi dir="auto">{label}</bdi>}
            htmlFor={id}
            required={required}
            validateStatus={message === null ? undefined : 'error'}
            help={
              message === null ? (
                help === '' ? undefined : (
                  <bdi dir="auto">{help}</bdi>
                )
              ) : (
                <span role="alert" data-testid={`error-custom-${field.key}`}>
                  {t(message.key, message.params as Record<string, string>)}
                </span>
              )
            }
          >
            <CustomFieldControl
              id={id}
              field={field}
              value={input.value ?? null}
              onChange={input.onChange}
              testId={`inc-custom-${field.key}`}
              ariaLabel={label}
            />
          </Form.Item>
        );
      }}
    />
  );
}
