import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { Button, Card, Checkbox, Flex, Form, Input, Select, Switch, Typography } from 'antd';

import type { CatalogQuestion, CatalogQuestionKind } from '@supportx/api-client';
import { lengthLimit, useLabel } from '@supportx/ui';

import { keyFrom } from './keys';

const KINDS: CatalogQuestionKind[] = [
  'text',
  'long_text',
  'choice',
  'multi_choice',
  'yes_no',
  'number',
  'decimal',
  'currency',
  'date',
  'datetime',
  'email',
  'phone',
  'url',
  'person',
  'attachment',
];
const AUDIENCES = ['requester', 'technician', 'approver'] as const;
const LANGUAGES = ['en', 'ar', 'ur'] as const;
const CHOICES = new Set<CatalogQuestionKind>(['choice', 'multi_choice']);

/** Per-language texts in three short inputs, each typed in its own direction. */
function Texts({
  value,
  onChange,
  testId,
  limit,
  required,
}: {
  value: Record<string, string> | undefined;
  onChange: (next: Record<string, string>) => void;
  testId: string;
  limit: number;
  required?: boolean;
}) {
  const t = useLabel();
  return (
    <Flex gap={8} wrap>
      {LANGUAGES.map((lang) => (
        <Input
          key={lang}
          lang={lang}
          dir={lang === 'en' ? 'ltr' : 'rtl'}
          style={{ flex: '1 1 180px' }}
          placeholder={t(`settings.name_in.${lang}`)}
          aria-label={t(`settings.name_in.${lang}`)}
          aria-required={required === true && lang === 'en'}
          count={lengthLimit(limit)}
          value={value?.[lang] ?? ''}
          onChange={(event) => {
            onChange({ ...(value ?? {}), [lang]: event.target.value });
          }}
          data-testid={`${testId}-${lang}`}
        />
      ))}
    </Flex>
  );
}

/**
 * The item's form (WP-031 plan D6): questions of every kind, each with its label, help and
 * choices per language, a starting value, required or not, and who sees it. Order with the
 * arrow buttons (keyboard), like every ordered list in the admin screens.
 */
export function QuestionsEditor({
  value,
  onChange,
  disabled,
}: {
  value: CatalogQuestion[];
  onChange: (next: CatalogQuestion[]) => void;
  disabled: boolean;
}) {
  const t = useLabel();
  const put = (index: number, next: Partial<CatalogQuestion>) => {
    onChange(value.map((q, i) => (i === index ? { ...q, ...next } : q)));
  };
  const move = (index: number, by: number) => {
    const next = [...value];
    const [moved] = next.splice(index, 1);
    if (moved === undefined) return;
    next.splice(index + by, 0, moved);
    onChange(next);
  };
  return (
    <Flex vertical gap={12} data-testid="cat-questions">
      {value.length === 0 && (
        <Typography.Text type="secondary">{t('catalog_admin.form.none')}</Typography.Text>
      )}
      {value.map((question, index) => (
        <Card
          key={`${question.key}-${String(index)}`}
          size="small"
          data-testid={`cat-question-${String(index)}`}
          title={
            <Typography.Text>
              {t('catalog_admin.form.question_n', { n: index + 1 })}
              {question.label.en ? ` · ${question.label.en}` : ''}
            </Typography.Text>
          }
          extra={
            <Flex gap={0}>
              <Button
                type="text"
                size="small"
                icon={<ArrowUpOutlined />}
                aria-label={t('catalog_admin.move_up')}
                disabled={disabled || index === 0}
                onClick={() => {
                  move(index, -1);
                }}
              />
              <Button
                type="text"
                size="small"
                icon={<ArrowDownOutlined />}
                aria-label={t('catalog_admin.move_down')}
                disabled={disabled || index === value.length - 1}
                onClick={() => {
                  move(index, 1);
                }}
              />
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
                aria-label={t('catalog_admin.form.remove')}
                disabled={disabled}
                onClick={() => {
                  onChange(value.filter((_, i) => i !== index));
                }}
                data-testid={`cat-question-${String(index)}-remove`}
              />
            </Flex>
          }
        >
          <Form layout="vertical" disabled={disabled} component="div">
            <Form.Item label={t('catalog_admin.form.label')} required>
              <Texts
                value={question.label}
                onChange={(label) => {
                  put(index, { label });
                }}
                testId={`cat-question-${String(index)}-label`}
                limit={120}
                required
              />
            </Form.Item>
            <Flex gap={12} wrap>
              <Form.Item
                label={t('catalog_admin.form.key')}
                help={t('catalog_admin.form.key_help')}
                style={{ minWidth: 200 }}
              >
                <Input
                  dir="ltr"
                  value={question.key}
                  count={lengthLimit(40)}
                  onChange={(event) => {
                    put(index, {
                      key: event.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_'),
                    });
                  }}
                  aria-label={t('catalog_admin.form.key')}
                  data-testid={`cat-question-${String(index)}-key`}
                />
              </Form.Item>
              <Form.Item label={t('catalog_admin.form.kind')} style={{ minWidth: 220 }}>
                <Select
                  value={question.kind}
                  onChange={(kind: CatalogQuestionKind) => {
                    put(index, {
                      kind,
                      options: CHOICES.has(kind) ? question.options : [],
                      option_labels: CHOICES.has(kind) ? question.option_labels : {},
                      default: null,
                    });
                  }}
                  options={KINDS.map((k) => ({ value: k, label: t(`catalog_question_kind.${k}`) }))}
                  aria-label={t('catalog_admin.form.kind')}
                  data-testid={`cat-question-${String(index)}-kind`}
                />
              </Form.Item>
              <Form.Item label={t('catalog_admin.form.required')}>
                <Switch
                  checked={question.required}
                  onChange={(required) => {
                    put(index, { required });
                  }}
                  aria-label={t('catalog_admin.form.required')}
                />
              </Form.Item>
              <Form.Item label={t('catalog_admin.form.shown_to')}>
                <Checkbox.Group
                  value={question.shown_to ?? [...AUDIENCES]}
                  onChange={(shown) => {
                    put(index, { shown_to: shown });
                  }}
                  options={AUDIENCES.map((a) => ({
                    value: a,
                    label: t(`catalog_question_audience.${a}`),
                  }))}
                />
              </Form.Item>
            </Flex>
            <Form.Item label={t('catalog_admin.form.help')}>
              <Texts
                value={question.help}
                onChange={(help) => {
                  put(index, { help });
                }}
                testId={`cat-question-${String(index)}-help`}
                limit={500}
              />
            </Form.Item>
            {CHOICES.has(question.kind) && (
              <Form.Item label={t('catalog_admin.form.options')}>
                <OptionsEditor
                  question={question}
                  onChange={(options, option_labels) => {
                    put(index, { options, option_labels });
                  }}
                  index={index}
                />
              </Form.Item>
            )}
          </Form>
        </Card>
      ))}
      <Button
        icon={<PlusOutlined />}
        disabled={disabled || value.length >= 30}
        onClick={() => {
          onChange([
            ...value,
            {
              key: keyFrom(
                `question ${String(value.length + 1)}`,
                new Set(value.map((q) => q.key)),
              ),
              label: {},
              kind: 'text',
              required: false,
              options: [],
              option_labels: {},
              help: {},
              default: null,
              shown_to: [...AUDIENCES],
            },
          ]);
        }}
        data-testid="cat-question-add"
        style={{ alignSelf: 'flex-start' }}
      >
        {t('catalog_admin.form.add')}
      </Button>
    </Flex>
  );
}

/** A choice question's options: each a stable code and its words per language. */
function OptionsEditor({
  question,
  onChange,
  index,
}: {
  question: CatalogQuestion;
  onChange: (options: string[], labels: Record<string, Record<string, string>>) => void;
  index: number;
}) {
  const t = useLabel();
  const options = question.options ?? [];
  const labels = question.option_labels ?? {};
  return (
    <Flex vertical gap={8}>
      {options.map((code, i) => (
        <Flex key={code} gap={8} align="center">
          <div style={{ flex: 1 }}>
            <Texts
              value={labels[code]}
              onChange={(words) => {
                onChange(options, { ...labels, [code]: words });
              }}
              testId={`cat-question-${String(index)}-option-${String(i)}`}
              limit={120}
              required
            />
          </div>
          <Button
            type="text"
            danger
            icon={<DeleteOutlined />}
            aria-label={t('catalog_admin.form.remove_option')}
            onClick={() => {
              const rest = Object.fromEntries(
                Object.entries(labels).filter(([option]) => option !== code),
              );
              onChange(
                options.filter((o) => o !== code),
                rest,
              );
            }}
          />
        </Flex>
      ))}
      <Button
        size="small"
        icon={<PlusOutlined />}
        style={{ alignSelf: 'flex-start' }}
        disabled={options.length >= 50}
        onClick={() => {
          const code = keyFrom(`option ${String(options.length + 1)}`, new Set(options));
          onChange([...options, code], { ...labels, [code]: {} });
        }}
        data-testid={`cat-question-${String(index)}-option-add`}
      >
        {t('catalog_admin.form.add_option')}
      </Button>
    </Flex>
  );
}
