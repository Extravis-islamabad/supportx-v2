import { Checkbox, DatePicker, Input, InputNumber, Radio, Select, Typography } from 'antd';
import dayjs from 'dayjs';
import type { ReactNode } from 'react';

import type { CatalogQuestion } from '@supportx/api-client';

import { useLabel } from '../appearance';
import { lengthLimit } from '../lengthLimit';
import { LONG_TEXT_MAX, TEXT_MAX, textIn, type QuestionValue } from './answers';

// One catalog form question, by its kind (WP-030 REQ-SR-003, WP-031 plan D6), for the console's
// raise page, the portal's request form and the admin preview. Values are what the API takes:
// text, a number, an ISO date (YYYY-MM-DD), an ISO date-time with its offset, a choice code or a
// list of codes, true/false, a person's ID, a list of stored file IDs. Labels, help and option
// words come in the reader's language with English as the fallback (plan D5).

export interface QuestionFieldProps {
  question: CatalogQuestion;
  value: QuestionValue;
  onChange: (value: QuestionValue) => void;
  locale: string;
  /** Read-only (the admin preview): shown as on the form, nothing can be typed. */
  disabled?: boolean;
  /** The app's own people picker (the console and the portal search people differently). */
  renderPerson?: (props: {
    id: string;
    value: string | null;
    onChange: (id: string | null) => void;
    disabled: boolean;
  }) => ReactNode;
  /** The app's own file upload (scanned files, by ID). */
  renderFiles?: (props: {
    id: string;
    value: string[];
    onChange: (ids: string[]) => void;
    disabled: boolean;
  }) => ReactNode;
}

function optionWords(question: CatalogQuestion, locale: string) {
  return (question.options ?? []).map((code) => ({
    value: code,
    label: textIn(question.option_labels?.[code], locale) || code,
  }));
}

/** The input for one question (the label and help are the caller's Form.Item's). */
export function QuestionField({
  question,
  value,
  onChange,
  locale,
  disabled = false,
  renderPerson,
  renderFiles,
}: QuestionFieldProps) {
  const t = useLabel();
  const id = `sr-q-${question.key}`;
  const label = textIn(question.label, locale) || question.key;
  const common = { id, 'aria-label': label, 'data-testid': id, disabled };
  const text = typeof value === 'string' ? value : '';
  switch (question.kind) {
    case 'choice':
      return (question.options ?? []).length <= 4 ? (
        <Radio.Group
          {...common}
          value={value}
          onChange={(event) => {
            onChange(event.target.value as string);
          }}
          options={optionWords(question, locale)}
        />
      ) : (
        <Select
          {...common}
          allowClear={!question.required}
          placeholder={t('catalog.form.choose')}
          value={typeof value === 'string' ? value : undefined}
          onChange={(next: string | undefined) => {
            onChange(next ?? null);
          }}
          options={optionWords(question, locale)}
        />
      );
    case 'multi_choice':
      return (
        <Checkbox.Group
          {...common}
          value={Array.isArray(value) ? value : []}
          onChange={(next) => {
            onChange(next);
          }}
          options={optionWords(question, locale)}
        />
      );
    case 'yes_no':
      return (
        <Radio.Group
          {...common}
          value={typeof value === 'boolean' ? value : undefined}
          onChange={(event) => {
            onChange(event.target.value as boolean);
          }}
          options={[
            { value: true, label: t('history.yes') },
            { value: false, label: t('history.no') },
          ]}
        />
      );
    case 'number':
    case 'decimal':
    case 'currency':
      return (
        <InputNumber
          {...common}
          style={{ width: 220 }}
          precision={question.kind === 'number' ? 0 : 2}
          value={typeof value === 'number' ? value : null}
          onChange={(next) => {
            onChange(typeof next === 'number' ? next : null);
          }}
        />
      );
    case 'date':
      return (
        <DatePicker
          {...common}
          value={text ? dayjs(text) : null}
          onChange={(next: dayjs.Dayjs | null) => {
            onChange(next ? next.format('YYYY-MM-DD') : null);
          }}
        />
      );
    case 'datetime':
      return (
        <DatePicker
          {...common}
          showTime={{ format: 'HH:mm' }}
          value={text ? dayjs(text) : null}
          onChange={(next: dayjs.Dayjs | null) => {
            // With the reader's offset: the API stores it in UTC (WP-026's rule).
            onChange(next ? next.format('YYYY-MM-DDTHH:mm:ssZ') : null);
          }}
        />
      );
    case 'long_text':
      return (
        <Input.TextArea
          {...common}
          autoSize={{ minRows: 3, maxRows: 10 }}
          count={lengthLimit(LONG_TEXT_MAX)}
          value={text}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      );
    case 'person':
      return renderPerson === undefined ? (
        <Typography.Text type="secondary">{t('catalog.form.person_later')}</Typography.Text>
      ) : (
        renderPerson({
          id,
          value: text || null,
          onChange: (next) => {
            onChange(next);
          },
          disabled,
        })
      );
    case 'attachment':
      return renderFiles === undefined ? (
        <Typography.Text type="secondary">{t('catalog.form.files_later')}</Typography.Text>
      ) : (
        renderFiles({
          id,
          value: Array.isArray(value) ? value : [],
          onChange: (next) => {
            onChange(next);
          },
          disabled,
        })
      );
    default:
      // text, e-mail, phone and web address: one line, typed in the reader's own way.
      return (
        <Input
          {...common}
          type={question.kind === 'email' ? 'email' : question.kind === 'url' ? 'url' : undefined}
          inputMode={question.kind === 'phone' ? 'tel' : undefined}
          dir={question.kind === 'text' ? undefined : 'ltr'}
          count={lengthLimit(TEXT_MAX)}
          value={text}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      );
  }
}
