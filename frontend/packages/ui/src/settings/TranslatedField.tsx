import { Badge, Form, Input } from 'antd';
import { useState } from 'react';

import { useLabel } from '../appearance';
import { lengthLimit } from '../lengthLimit';
import { Tabs } from '../layout/Tabs';

export type TranslatedValue = Partial<Record<'en' | 'ar' | 'ur', string>>;

const LANGUAGES = ['en', 'ar', 'ur'] as const;

/**
 * One translatable name (QA6S-SVC-12 and the proposal's `TranslatedField`): the label once and a
 * tab per language (English, العربية, اردو), each input in its own direction. English is required
 * unless `required` says otherwise; the same rule everywhere.
 */
export function TranslatedField({
  label,
  value = {},
  onChange,
  required = ['en'],
  max = 200,
  error,
  testId,
}: {
  label: string;
  value?: TranslatedValue;
  onChange: (next: TranslatedValue) => void;
  required?: readonly ('en' | 'ar' | 'ur')[];
  max?: number;
  /** The field's error, already translated: one for the field, or one per language (the server
   * may refuse the Arabic alone); shown under the field, and the language's tab is marked. */
  error?: string | TranslatedValue;
  testId?: string;
}) {
  const t = useLabel();
  const [tab, setTab] = useState<(typeof LANGUAGES)[number]>('en');
  const perLanguage = typeof error === 'object' ? error : {};
  const message =
    typeof error === 'string'
      ? error
      : LANGUAGES.filter((lang) => perLanguage[lang] !== undefined)
          .map((lang) => `${t(`locale.${lang}`)}: ${perLanguage[lang] ?? ''}`)
          .join(' ') || undefined;
  return (
    <Form.Item
      label={label}
      required={required.length > 0}
      validateStatus={message === undefined ? undefined : 'error'}
      help={message}
      data-testid={testId}
    >
      <Tabs
        size="small"
        activeKey={tab}
        onChange={(key) => {
          setTab(key as (typeof LANGUAGES)[number]);
        }}
        items={LANGUAGES.map((lang) => ({
          key: lang,
          label: (
            <span>
              {`${t(`locale.${lang}`)}${required.includes(lang) ? ' *' : ''}`}
              {perLanguage[lang] !== undefined && (
                <Badge status="error" style={{ marginInlineStart: 4 }} aria-hidden />
              )}
            </span>
          ),
          children: (
            <Input
              aria-label={`${label} (${t(`locale.${lang}`)})`}
              dir={lang === 'en' ? 'ltr' : 'rtl'}
              lang={lang}
              count={lengthLimit(max)}
              value={value[lang] ?? ''}
              onChange={(event) => {
                onChange({ ...value, [lang]: event.target.value });
              }}
              data-testid={testId === undefined ? undefined : `${testId}-${lang}`}
            />
          ),
        }))}
      />
    </Form.Item>
  );
}
