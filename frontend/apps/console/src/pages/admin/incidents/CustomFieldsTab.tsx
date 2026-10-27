import { ArrowDownOutlined, ArrowUpOutlined } from '@ant-design/icons';
import {
  App,
  Button,
  Card,
  Checkbox,
  Collapse,
  Drawer,
  Flex,
  Form,
  Input,
  Modal,
  Radio,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useCustomFieldChange,
  useCustomFields,
  type CustomField,
  type CustomFieldChange,
  type CustomFieldChoice,
  type CustomFieldType,
  type Labels,
} from '@supportx/api-client';
import { EmptyText, reportError, useAppearance, useLabel, WriteButton } from '@supportx/ui';

import { CustomFieldControl } from '../../customFields/fields';
import { fieldName, filled, localized } from '../../customFields/values';
import { cleanLabels, fieldMessages } from './helpers';
import { LabelsFields, Problems } from './shared';

const TYPES: CustomFieldType[] = [
  'text',
  'long_text',
  'integer',
  'decimal',
  'currency',
  'date',
  'datetime',
  'choice',
  'multi_choice',
  'yes_no',
  'email',
  'phone',
  'url',
  'person',
];
const CHOICE_TYPES = new Set<CustomFieldType>(['choice', 'multi_choice']);
const NUMBER_TYPES = new Set<CustomFieldType>(['integer', 'decimal', 'currency']);
const TEXT_TYPES = new Set<CustomFieldType>(['text', 'long_text']);
const LANGUAGES = ['en', 'ar', 'ur'] as const;

/**
 * Custom fields on incidents (WP-026, REQ-INC-014): add a field of any type with its name and
 * help in each language, then place it on templates. A field records hold values in can be
 * retired (kept on old records, not offered) or removed after a confirmation (AC4); a field
 * filtered often can be indexed without a code change (AC2). Changes reach every open form,
 * record and list live.
 */
export function CustomFieldsTab() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message, modal } = App.useApp();
  const fields = useCustomFields('incident');
  const change = useCustomFieldChange();
  const [editing, setEditing] = useState<CustomField | 'new' | null>(null);
  const [removing, setRemoving] = useState<CustomField | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const all = fields.data ?? [];
  const run = (next: CustomFieldChange, onDone?: () => void) => {
    setProblems([]);
    change.mutate(next, {
      onSuccess: () => {
        void message.success(t('settings.saved'));
        onDone?.();
      },
      onError: (error) => {
        if (error instanceof ApiError && error.code === 'version_conflict') {
          void message.warning(t('settings.changed_elsewhere'));
          return;
        }
        const found = fieldMessages(t, error);
        if (found.length > 0) {
          setProblems(found);
          return;
        }
        reportError(error);
      },
    });
  };
  const move = (index: number, by: -1 | 1) => {
    const ids = all.map((f) => f.id);
    const [moved] = ids.splice(index, 1);
    if (moved === undefined) return;
    ids.splice(index + by, 0, moved);
    run({ kind: 'order', entity: 'incident', ids });
  };
  const remove = (field: CustomField) => {
    if (field.in_use) {
      // AC4 (D-087): a field in use asks first; retiring is the recommended answer.
      setRemoving(field);
      return;
    }
    void modal.confirm({
      title: t('custom_fields.remove_title', { name: fieldName(field, locale) }),
      content: t('custom_fields.remove_unused'),
      okText: t('custom_fields.remove'),
      okButtonProps: {
        danger: true,
        ...({ 'data-testid': 'cf-remove-ok' } as Record<string, string>),
      },
      cancelText: t('actions.cancel'),
      onOk: () => {
        run({ kind: 'delete', id: field.id, version: field.version, confirm: false });
      },
    });
  };
  return (
    <Card
      title={t('custom_fields.title')}
      extra={
        <WriteButton
          type="primary"
          onClick={() => {
            setProblems([]);
            setEditing('new');
          }}
          data-testid="cf-new"
        >
          {t('custom_fields.new')}
        </WriteButton>
      }
      data-testid="settings-custom-fields"
    >
      <Typography.Paragraph type="secondary">{t('custom_fields.help')}</Typography.Paragraph>
      {editing === null && <Problems problems={problems} testId="cf-problems" />}
      <Table
        size="small"
        rowKey="id"
        loading={fields.isPending}
        pagination={false}
        dataSource={all}
        locale={{ emptyText: <EmptyText>{t('custom_fields.none')}</EmptyText> }}
        columns={[
          {
            key: 'name',
            title: t('settings.name'),
            render: (_: unknown, f: CustomField) => (
              <Flex gap={6} align="center" wrap>
                <bdi dir="auto" data-testid={`cf-name-${f.key}`}>
                  {fieldName(f, locale)}
                </bdi>
                {f.retired && (
                  <Tag data-testid={`cf-retired-${f.key}`}>{t('custom_fields.retired')}</Tag>
                )}
                {f.validation.required && <Tag color="blue">{t('custom_fields.required')}</Tag>}
              </Flex>
            ),
          },
          {
            key: 'type',
            title: t('custom_fields.type'),
            render: (_: unknown, f: CustomField) => t(`custom_field_type.${f.field_type}`),
          },
          {
            key: 'use',
            title: t('custom_fields.in_use'),
            render: (_: unknown, f: CustomField) =>
              f.in_use ? t('custom_fields.yes') : t('custom_fields.no'),
          },
          {
            key: 'index',
            title: t('custom_fields.index'),
            render: (_: unknown, f: CustomField) => (
              <IndexTag field={f} testId={`cf-index-${f.key}`} />
            ),
          },
          {
            key: 'actions',
            title: t('settings.actions'),
            render: (_: unknown, f: CustomField, index: number) => (
              <Space wrap size={4}>
                <Button
                  size="small"
                  onClick={() => {
                    setProblems([]);
                    setEditing(f);
                  }}
                  data-testid={`cf-edit-${f.key}`}
                >
                  {t('actions.edit')}
                </Button>
                <Button
                  size="small"
                  icon={<ArrowUpOutlined />}
                  disabled={index === 0 || change.isPending}
                  aria-label={t('settings.move_up', { name: fieldName(f, locale) })}
                  onClick={() => {
                    move(index, -1);
                  }}
                  data-testid={`cf-up-${f.key}`}
                />
                <Button
                  size="small"
                  icon={<ArrowDownOutlined />}
                  disabled={index === all.length - 1 || change.isPending}
                  aria-label={t('settings.move_down', { name: fieldName(f, locale) })}
                  onClick={() => {
                    move(index, 1);
                  }}
                  data-testid={`cf-down-${f.key}`}
                />
                <Button
                  size="small"
                  onClick={() => {
                    run({
                      kind: 'update',
                      id: f.id,
                      version: f.version,
                      body: { retired: !f.retired },
                    });
                  }}
                  data-testid={`cf-retire-${f.key}`}
                >
                  {f.retired ? t('custom_fields.restore') : t('custom_fields.retire')}
                </Button>
                <Button
                  size="small"
                  danger
                  onClick={() => {
                    remove(f);
                  }}
                  data-testid={`cf-remove-${f.key}`}
                >
                  {t('custom_fields.remove')}
                </Button>
              </Space>
            ),
          },
        ]}
        scroll={{ x: 'max-content' }}
      />
      {editing !== null && (
        <CustomFieldEditor
          key={editing === 'new' ? 'new' : editing.id}
          // The saved field as it is now (index progress arrives live); the draft keeps edits.
          field={editing === 'new' ? null : (all.find((f) => f.id === editing.id) ?? editing)}
          pending={change.isPending}
          problems={problems}
          onClose={() => {
            setEditing(null);
            setProblems([]);
          }}
          onSave={(next) => {
            run(next, () => {
              setEditing(null);
            });
          }}
          onIndex={(field) => {
            run({ kind: 'index', id: field.id, version: field.version }, () => {
              setEditing(null);
            });
          }}
        />
      )}
      <Modal
        open={removing !== null}
        title={
          removing === null
            ? ''
            : t('custom_fields.remove_title', { name: fieldName(removing, locale) })
        }
        onCancel={() => {
          setRemoving(null);
        }}
        destroyOnHidden
        data-testid="cf-remove-dialog"
        footer={
          removing === null
            ? null
            : [
                <Button
                  key="cancel"
                  onClick={() => {
                    setRemoving(null);
                  }}
                >
                  {t('actions.cancel')}
                </Button>,
                <Button
                  key="remove"
                  danger
                  type={removing.retired ? 'primary' : 'default'}
                  onClick={() => {
                    run({
                      kind: 'delete',
                      id: removing.id,
                      version: removing.version,
                      confirm: true,
                    });
                    setRemoving(null);
                  }}
                  data-testid="cf-remove-ok"
                >
                  {t('custom_fields.remove_anyway')}
                </Button>,
                ...(removing.retired
                  ? []
                  : [
                      <Button
                        key="retire"
                        type="primary"
                        autoFocus
                        onClick={() => {
                          run({
                            kind: 'update',
                            id: removing.id,
                            version: removing.version,
                            body: { retired: true },
                          });
                          setRemoving(null);
                        }}
                        data-testid="cf-retire-recommended"
                      >
                        {t('custom_fields.retire_recommended')}
                      </Button>,
                    ]),
              ]
        }
      >
        <Typography.Paragraph>{t('custom_fields.remove_in_use')}</Typography.Paragraph>
      </Modal>
    </Card>
  );
}

interface Draft {
  field_type: CustomFieldType;
  labels: Labels;
  help: Labels;
  choices: CustomFieldChoice[];
  display: 'list' | 'radio';
  required: boolean;
  min: string;
  max: string;
  min_length: string;
  max_length: string;
  pattern: string;
  currency: string;
  default: unknown;
}

function draftOf(field: CustomField | null): Draft {
  return {
    field_type: field?.field_type ?? 'text',
    labels: field?.labels ?? {},
    help: field?.help ?? {},
    choices: field?.choices ?? [],
    display: field?.display ?? 'list',
    required: field?.validation.required ?? false,
    min: field?.validation.min ?? '',
    max: field?.validation.max ?? '',
    min_length: field?.validation.min_length == null ? '' : String(field.validation.min_length),
    max_length: field?.validation.max_length == null ? '' : String(field.validation.max_length),
    pattern: field?.validation.pattern ?? '',
    currency: field?.currency ?? '',
    default: field?.default ?? null,
  };
}

const blank = (value: string) => (value.trim() === '' ? null : value.trim());
const whole = (value: string) => (value.trim() === '' ? null : Number(value));

/** The body of a save: only what this type uses. */
function bodyOf(draft: Draft) {
  const kind = draft.field_type;
  return {
    labels: cleanLabels(draft.labels) ?? {},
    help: cleanLabels(draft.help),
    choices: CHOICE_TYPES.has(kind)
      ? draft.choices.map((c) => ({ ...c, labels: cleanLabels(c.labels) ?? {} }))
      : [],
    display: draft.display,
    default: filled(draft.default) ? draft.default : null,
    validation: {
      required: draft.required,
      min: NUMBER_TYPES.has(kind) ? blank(draft.min) : null,
      max: NUMBER_TYPES.has(kind) ? blank(draft.max) : null,
      min_length: TEXT_TYPES.has(kind) ? whole(draft.min_length) : null,
      max_length: TEXT_TYPES.has(kind) ? whole(draft.max_length) : null,
      pattern: kind === 'text' ? blank(draft.pattern) : null,
    },
    currency: kind === 'currency' ? blank(draft.currency.toUpperCase()) : null,
  };
}

function CustomFieldEditor({
  field,
  pending,
  problems,
  onClose,
  onSave,
  onIndex,
}: {
  field: CustomField | null;
  pending: boolean;
  problems: string[];
  onClose: () => void;
  onSave: (change: CustomFieldChange) => void;
  onIndex: (field: CustomField) => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const [draft, setDraft] = useState<Draft>(() => draftOf(field));
  const set = (patch: Partial<Draft>) => {
    setDraft((current) => ({ ...current, ...patch }));
  };
  const kind = draft.field_type;
  // A preview of the field as forms will show it: the default value is chosen in it.
  const preview: CustomField = {
    ...(field ?? {
      id: 'new',
      entity: 'incident',
      key: '',
      sort_order: 0,
      retired: false,
      removed: false,
      in_use: false,
      index_state: 'none',
      index_error: null,
      version: 0,
    }),
    ...bodyOf(draft),
    field_type: kind,
    labels: draft.labels,
    help: draft.help,
    choices: draft.choices,
    display: draft.display,
  };
  const save = () => {
    const body = bodyOf(draft);
    if (field === null) {
      onSave({ kind: 'create', body: { entity: 'incident', field_type: kind, ...body } });
    } else {
      onSave({ kind: 'update', id: field.id, version: field.version, body });
    }
  };
  return (
    <Drawer
      open
      width={560}
      title={field === null ? t('custom_fields.new') : fieldName(field, locale)}
      onClose={onClose}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={onClose}>{t('actions.cancel')}</Button>
          <WriteButton type="primary" loading={pending} onClick={save} data-testid="cf-save">
            {t('actions.save')}
          </WriteButton>
        </Space>
      }
      data-testid="cf-editor"
    >
      <Problems problems={problems} testId="cf-editor-problems" />
      <Form layout="vertical" component="div">
        <Form.Item
          label={t('custom_fields.type')}
          htmlFor="cf-type"
          help={field === null ? undefined : t('custom_fields.type_fixed')}
        >
          <Select
            id="cf-type"
            value={kind}
            disabled={field !== null}
            onChange={(next: CustomFieldType) => {
              set({ field_type: next, default: null });
            }}
            options={TYPES.map((value) => ({ value, label: t(`custom_field_type.${value}`) }))}
            data-testid="cf-type"
          />
        </Form.Item>
        <LabelsFields
          value={draft.labels}
          onChange={(labels) => {
            set({ labels });
          }}
          testId="cf-label"
        />
        {LANGUAGES.map((language) => (
          <Form.Item
            key={language}
            label={t(`custom_fields.help_in.${language}`)}
            htmlFor={`cf-help-${language}`}
          >
            <Input
              id={`cf-help-${language}`}
              dir={language === 'en' ? 'ltr' : 'rtl'}
              lang={language}
              maxLength={300}
              value={draft.help[language] ?? ''}
              onChange={(event) => {
                set({ help: { ...draft.help, [language]: event.target.value } });
              }}
              data-testid={`cf-help-${language}`}
            />
          </Form.Item>
        ))}
        {CHOICE_TYPES.has(kind) && (
          <>
            <ChoicesEditor
              value={draft.choices}
              onChange={(choices) => {
                set({ choices });
              }}
            />
            <Form.Item label={t('custom_fields.display')}>
              <Radio.Group
                value={draft.display}
                onChange={(event) => {
                  set({ display: event.target.value as Draft['display'] });
                }}
                options={(['list', 'radio'] as const).map((value) => ({
                  value,
                  label: t(`custom_field_display.${value}`),
                }))}
                data-testid="cf-display"
              />
            </Form.Item>
          </>
        )}
        <Form.Item>
          <Checkbox
            checked={draft.required}
            onChange={(event) => {
              set({ required: event.target.checked });
            }}
            data-testid="cf-required"
          >
            {t('custom_fields.always_required')}
          </Checkbox>
          <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
            {t('custom_fields.required_help')}
          </Typography.Paragraph>
        </Form.Item>
        {NUMBER_TYPES.has(kind) && (
          <Flex gap={12} wrap>
            <Form.Item label={t('custom_fields.min')} htmlFor="cf-min">
              <Input
                id="cf-min"
                dir="ltr"
                inputMode="decimal"
                value={draft.min}
                onChange={(event) => {
                  set({ min: event.target.value });
                }}
                data-testid="cf-min"
              />
            </Form.Item>
            <Form.Item label={t('custom_fields.max')} htmlFor="cf-max">
              <Input
                id="cf-max"
                dir="ltr"
                inputMode="decimal"
                value={draft.max}
                onChange={(event) => {
                  set({ max: event.target.value });
                }}
                data-testid="cf-max"
              />
            </Form.Item>
          </Flex>
        )}
        {kind === 'currency' && (
          <Form.Item
            label={t('custom_fields.currency')}
            htmlFor="cf-currency"
            required
            help={t('custom_fields.currency_help')}
          >
            <Input
              id="cf-currency"
              dir="ltr"
              maxLength={3}
              style={{ width: 120, textTransform: 'uppercase' }}
              value={draft.currency}
              onChange={(event) => {
                set({ currency: event.target.value.toUpperCase() });
              }}
              data-testid="cf-currency"
            />
          </Form.Item>
        )}
        {TEXT_TYPES.has(kind) && (
          <Flex gap={12} wrap>
            <Form.Item label={t('custom_fields.min_length')} htmlFor="cf-min-length">
              <Input
                id="cf-min-length"
                dir="ltr"
                inputMode="numeric"
                value={draft.min_length}
                onChange={(event) => {
                  set({ min_length: event.target.value.replace(/\D/g, '') });
                }}
                data-testid="cf-min-length"
              />
            </Form.Item>
            <Form.Item label={t('custom_fields.max_length')} htmlFor="cf-max-length">
              <Input
                id="cf-max-length"
                dir="ltr"
                inputMode="numeric"
                value={draft.max_length}
                onChange={(event) => {
                  set({ max_length: event.target.value.replace(/\D/g, '') });
                }}
                data-testid="cf-max-length"
              />
            </Form.Item>
          </Flex>
        )}
        {kind === 'text' && (
          <Form.Item
            label={t('custom_fields.pattern')}
            htmlFor="cf-pattern"
            help={t('custom_fields.pattern_help')}
          >
            <Input
              id="cf-pattern"
              dir="ltr"
              maxLength={200}
              value={draft.pattern}
              onChange={(event) => {
                set({ pattern: event.target.value });
              }}
              data-testid="cf-pattern"
            />
          </Form.Item>
        )}
        {kind !== 'person' && (
          <Form.Item
            label={t('custom_fields.default')}
            htmlFor="cf-default"
            help={t('custom_fields.default_help')}
          >
            <CustomFieldControl
              id="cf-default"
              field={preview}
              value={draft.default}
              onChange={(value) => {
                set({ default: value });
              }}
              testId="cf-default"
              ariaLabel={t('custom_fields.default')}
            />
          </Form.Item>
        )}
        {field !== null && (
          <Collapse
            size="small"
            items={[
              {
                key: 'advanced',
                label: t('custom_fields.advanced'),
                children: (
                  <Flex vertical gap={12}>
                    <div>
                      <Typography.Text type="secondary">
                        {t('custom_fields.api_name')}
                      </Typography.Text>
                      <br />
                      <Typography.Text code copyable dir="ltr" data-testid="cf-api-name">
                        {`custom.${field.key}`}
                      </Typography.Text>
                    </div>
                    <div>
                      <Typography.Paragraph type="secondary" style={{ marginBottom: 4 }}>
                        {t('custom_fields.index_help')}
                      </Typography.Paragraph>
                      <Space wrap>
                        <IndexTag field={field} testId="cf-editor-index-state" />
                        {(field.index_state === 'none' || field.index_state === 'failed') && (
                          <WriteButton
                            size="small"
                            onClick={() => {
                              onIndex(field);
                            }}
                            data-testid="cf-request-index"
                          >
                            {field.index_state === 'failed'
                              ? t('custom_fields.request_again')
                              : t('custom_fields.request_index')}
                          </WriteButton>
                        )}
                      </Space>
                      {field.index_state === 'failed' && (
                        <Typography.Paragraph
                          type="danger"
                          style={{ marginTop: 4 }}
                          data-testid="cf-index-failure"
                        >
                          {t('custom_fields.index_failed', {
                            reason: t(
                              `custom_field_index_error.${field.index_error ?? 'unexpected'}`,
                            ),
                          })}
                        </Typography.Paragraph>
                      )}
                    </div>
                  </Flex>
                ),
              },
            ]}
          />
        )}
      </Form>
    </Drawer>
  );
}

/** The choices of a pick list: names per language; a removed choice stays, retired. */
function ChoicesEditor({
  value,
  onChange,
}: {
  value: CustomFieldChoice[];
  onChange: (next: CustomFieldChoice[]) => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const [adding, setAdding] = useState<Labels | null>(null);
  const update = (index: number, patch: Partial<CustomFieldChoice>) => {
    onChange(value.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  };
  return (
    <Form.Item label={t('custom_fields.choices')} required>
      <Flex vertical gap={6} data-testid="cf-choices">
        {value.map((choice, index) => (
          <Flex key={choice.code ?? `new-${String(index)}`} gap={6} align="center" wrap>
            <Input
              aria-label={t('settings.name_in.en')}
              dir="ltr"
              lang="en"
              maxLength={120}
              style={{ flex: '1 1 160px' }}
              value={choice.labels.en ?? ''}
              onChange={(event) => {
                update(index, { labels: { ...choice.labels, en: event.target.value } });
              }}
              data-testid={`cf-choice-en-${String(index)}`}
            />
            <Input
              aria-label={t('settings.name_in.ar')}
              dir="rtl"
              lang="ar"
              maxLength={120}
              style={{ flex: '1 1 120px' }}
              value={choice.labels.ar ?? ''}
              onChange={(event) => {
                update(index, { labels: { ...choice.labels, ar: event.target.value } });
              }}
              data-testid={`cf-choice-ar-${String(index)}`}
            />
            <Input
              aria-label={t('settings.name_in.ur')}
              dir="rtl"
              lang="ur"
              maxLength={120}
              style={{ flex: '1 1 120px' }}
              value={choice.labels.ur ?? ''}
              onChange={(event) => {
                update(index, { labels: { ...choice.labels, ur: event.target.value } });
              }}
              data-testid={`cf-choice-ur-${String(index)}`}
            />
            {choice.code === null || choice.code === undefined ? (
              <Button
                size="small"
                onClick={() => {
                  onChange(value.filter((_, i) => i !== index));
                }}
                data-testid={`cf-choice-drop-${String(index)}`}
              >
                {t('custom_fields.remove')}
              </Button>
            ) : (
              <Checkbox
                checked={choice.retired}
                onChange={(event) => {
                  update(index, { retired: event.target.checked });
                }}
                data-testid={`cf-choice-retired-${String(index)}`}
              >
                {t('custom_fields.retired')}
              </Checkbox>
            )}
          </Flex>
        ))}
        {adding === null ? (
          <Button
            onClick={() => {
              setAdding({});
            }}
            style={{ alignSelf: 'flex-start' }}
            data-testid="cf-choice-add"
          >
            {t('custom_fields.add_choice')}
          </Button>
        ) : (
          <Modal
            open
            title={t('custom_fields.add_choice')}
            okText={t('actions.add')}
            cancelText={t('actions.cancel')}
            onCancel={() => {
              setAdding(null);
            }}
            okButtonProps={{ disabled: (adding.en ?? '').trim() === '' }}
            onOk={() => {
              onChange([
                ...value,
                { code: null, labels: cleanLabels(adding) ?? {}, retired: false },
              ]);
              setAdding(null);
            }}
            destroyOnHidden
            data-testid="cf-choice-dialog"
          >
            <Form layout="vertical" component="div">
              <LabelsFields value={adding} onChange={setAdding} testId="cf-choice-name" />
            </Form>
          </Modal>
        )}
        {value.length > 0 && (
          <Typography.Text type="secondary">
            {t('custom_fields.choices_help', {
              names: value
                .filter((c) => !c.retired)
                .map((c) => localized(c.labels, locale))
                .join(', '),
            })}
          </Typography.Text>
        )}
      </Flex>
    </Form.Item>
  );
}

const INDEX_COLOURS: Record<CustomField['index_state'], string | undefined> = {
  none: undefined,
  pending: 'gold',
  building: 'processing',
  active: 'green',
  failed: 'red',
};

/** Where a field's index is (D-088), live; a failure says why on hover. */
function IndexTag({ field, testId }: { field: CustomField; testId: string }) {
  const t = useLabel();
  const tag = (
    <Tag color={INDEX_COLOURS[field.index_state]} data-testid={testId}>
      {t(`custom_field_index_state.${field.index_state}`)}
    </Tag>
  );
  if (field.index_state !== 'failed') return tag;
  return (
    <Tooltip title={t(`custom_field_index_error.${field.index_error ?? 'unexpected'}`)}>
      {tag}
    </Tooltip>
  );
}
