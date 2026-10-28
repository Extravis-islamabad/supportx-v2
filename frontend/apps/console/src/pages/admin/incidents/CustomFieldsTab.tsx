import { ArrowDownOutlined, ArrowUpOutlined } from '@ant-design/icons';
import {
  Alert,
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
  Tooltip,
  Typography,
} from 'antd';
import { Fragment, useState } from 'react';

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
import {
  ConflictDialog,
  EmptyText,
  lengthLimit,
  markHandled,
  reportError,
  ToneTag,
  useAppearance,
  useConflict,
  useDateTime,
  useLabel,
  WriteButton,
  type Tone,
} from '@supportx/ui';

import { CustomFieldControl } from '../../customFields/fields';
import { fieldName, filled, localized } from '../../customFields/values';
import { cleanLabels, refusalMessages } from './helpers';
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
  // Problems of the last save, each with the field it belongs to (shown there: QA BUG-08).
  const [errors, setErrors] = useState<FieldProblem[]>([]);
  const all = fields.data ?? [];
  // A list action (remove, index) on a field someone changed first (409): the shared dialog
  // (QA WP-029 BUG-05); "Keep my changes" runs it again on the saved version.
  const conflict = useConflict();
  const [tried, setTried] = useState<{ next: CustomFieldChange; opened?: CustomField }>();
  const triedId = tried !== undefined && 'id' in tried.next ? tried.next.id : undefined;
  const live = all.find((f) => f.id === triedId);
  const run = (
    next: CustomFieldChange,
    onDone?: () => void,
    onConflict?: (error: ApiError) => void,
  ) => {
    setErrors([]);
    change.mutate(next, {
      onSuccess: () => {
        void message.success(t('settings.saved'));
        onDone?.();
      },
      onError: (error) => {
        if (error instanceof ApiError && error.code === 'version_conflict') {
          if (onConflict !== undefined) {
            onConflict(error);
          } else if (conflict.take(error)) {
            const id = 'id' in next ? next.id : undefined;
            setTried({ next, opened: all.find((f) => f.id === id) });
          }
          return;
        }
        if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
          markHandled(error);
          setErrors(
            error.fieldErrors.map((f) => ({
              field: f.field.replace(/^body\./, ''),
              text: t(f.message_key, f.params ?? {}),
            })),
          );
          return;
        }
        // Any other refusal (a rule, a limit) is shown with them, once (QA WP-029 BUG-02).
        const refused = refusalMessages(t, error, []);
        if (refused.length > 0) {
          setErrors(refused.map((text) => ({ field: '', text })));
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
            setErrors([]);
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
      {editing === null && <Problems problems={errors.map((e) => e.text)} testId="cf-problems" />}
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
                  <ToneTag tone="default" testId={`cf-retired-${f.key}`}>
                    {t('custom_fields.retired')}
                  </ToneTag>
                )}
                {f.validation.required && (
                  <ToneTag tone="info">{t('custom_fields.required')}</ToneTag>
                )}
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
                    setErrors([]);
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
          errors={errors}
          onEdit={() => {
            if (errors.length > 0) setErrors([]);
          }}
          onClose={() => {
            setEditing(null);
            setErrors([]);
          }}
          onSave={(next, onConflict) => {
            run(
              next,
              () => {
                setEditing(null);
              },
              onConflict,
            );
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
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={(name) => t(`custom_fields.part.${name}`)}
        opened={fieldView(tried?.opened)}
        latest={fieldView(live)}
        onReload={() => {
          conflict.clear();
          setTried(undefined);
        }}
        onKeepMine={() => {
          conflict.clear();
          const next = tried?.next;
          const version = conflict.latestVersion ?? live?.version;
          if (next !== undefined && 'version' in next && version !== undefined) {
            run({ ...next, version });
          }
          setTried(undefined);
        }}
      />
    </Card>
  );
}

/** A field's parts as the editor names them, for the conflict dialog (QA WP-029 BUG-05). */
function fieldView(field: CustomField | null | undefined): object | undefined {
  if (field == null) return undefined;
  return {
    field_type: field.field_type,
    labels: field.labels,
    help: field.help,
    choices: field.choices,
    display: field.display,
    validation: field.validation,
    default_value: field.default,
    currency: field.currency,
    retired_at: field.retired,
    sort_order: field.sort_order,
  };
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

interface FieldProblem {
  field: string;
  text: string;
}

/** Problems at `path` or inside it ("choices" covers "choices[0].labels"). */
function problemsAt(errors: FieldProblem[], ...paths: string[]): string | undefined {
  const found = errors.filter((e) =>
    paths.some((p) => e.field === p || e.field.startsWith(`${p}.`) || e.field.startsWith(`${p}[`)),
  );
  return found.length === 0 ? undefined : found.map((e) => e.text).join(' ');
}

const EDITOR_PATHS = [
  'labels',
  'help',
  'field_type',
  'choices',
  'display',
  'validation',
  'currency',
  'default',
  'key',
];

function CustomFieldEditor({
  field,
  pending,
  errors,
  onEdit,
  onClose,
  onSave,
  onIndex,
}: {
  field: CustomField | null;
  pending: boolean;
  errors: FieldProblem[];
  onEdit: () => void;
  onClose: () => void;
  onSave: (change: CustomFieldChange, onConflict: (error: ApiError) => void) => void;
  onIndex: (field: CustomField) => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const dates = useDateTime();
  const [draft, setDraft] = useState<Draft>(() => draftOf(field));
  // The field as it was when the editor opened: its version goes with the save. A save made
  // elsewhere meanwhile is said at once and the save asks what to keep (QA BUG-01).
  const [base, setBase] = useState<CustomField | null>(field);
  const [conflict, setConflict] = useState<ApiError | null>(null);
  const changedElsewhere = field !== null && base !== null && field.version !== base.version;
  const set = (patch: Partial<Draft>) => {
    onEdit(); // the problems shown were about the values before this edit (QA BUG-04)
    setDraft((current) => ({ ...current, ...patch }));
  };
  const at = (...paths: string[]) => problemsAt(errors, ...paths);
  const elsewhere = errors
    .filter((e) => !EDITOR_PATHS.some((p) => problemsAt([e], p) !== undefined))
    .map((e) => e.text);
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
  const save = (version = base?.version ?? 0) => {
    const body = bodyOf(draft);
    if (field === null) {
      onSave(
        { kind: 'create', body: { entity: 'incident', field_type: kind, ...body } },
        setConflict,
      );
    } else {
      onSave({ kind: 'update', id: field.id, version, body }, setConflict);
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
          <WriteButton
            type="primary"
            loading={pending}
            onClick={() => {
              save();
            }}
            data-testid="cf-save"
          >
            {t('actions.save')}
          </WriteButton>
        </Space>
      }
      data-testid="cf-editor"
    >
      {changedElsewhere && (
        <Alert
          type="warning"
          showIcon
          role="status"
          style={{ marginBottom: 12 }}
          message={t('custom_fields.changed_by', {
            name: field.changed_by ?? t('custom_fields.someone'),
            at: dates.format(field.changed_at),
          })}
          data-testid="cf-changed-by"
        />
      )}
      <Problems problems={elsewhere} testId="cf-editor-problems" />
      <Form layout="vertical" component="div">
        {field === null ? (
          <Form.Item
            label={t('custom_fields.type')}
            htmlFor="cf-type"
            validateStatus={at('field_type') === undefined ? undefined : 'error'}
            help={at('field_type')}
          >
            <Select
              id="cf-type"
              value={kind}
              onChange={(next: CustomFieldType) => {
                set({ field_type: next, default: null });
              }}
              options={TYPES.map((value) => ({ value, label: t(`custom_field_type.${value}`) }))}
              data-testid="cf-type"
            />
          </Form.Item>
        ) : (
          // Read-only text, not a disabled control (QA C6): the type never changes.
          <Form.Item label={t('custom_fields.type')} help={t('custom_fields.type_fixed')}>
            <Typography.Text data-testid="cf-type-fixed">
              {t(`custom_field_type.${kind}`)}
            </Typography.Text>
          </Form.Item>
        )}
        <LabelsFields
          value={draft.labels}
          onChange={(labels) => {
            set({ labels });
          }}
          testId="cf-label"
        />
        {at('labels', 'key') !== undefined && (
          <Typography.Paragraph type="danger" role="alert" data-testid="cf-error-labels">
            {at('labels', 'key')}
          </Typography.Paragraph>
        )}
        {LANGUAGES.map((language) => (
          <Form.Item
            key={language}
            label={t(`custom_fields.help_in.${language}`)}
            htmlFor={`cf-help-${language}`}
            validateStatus={language === 'en' && at('help') !== undefined ? 'error' : undefined}
            help={language === 'en' ? at('help') : undefined}
          >
            <Input
              id={`cf-help-${language}`}
              dir={language === 'en' ? 'ltr' : 'rtl'}
              lang={language}
              count={lengthLimit(300)}
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
              problem={at('choices')}
            />
            <Form.Item
              label={t('custom_fields.display')}
              validateStatus={at('display') === undefined ? undefined : 'error'}
              help={at('display')}
            >
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
          {errors.some((e) => e.field === 'validation') && (
            <Typography.Paragraph type="danger" role="alert" style={{ margin: 0 }}>
              {errors
                .filter((e) => e.field === 'validation')
                .map((e) => e.text)
                .join(' ')}
            </Typography.Paragraph>
          )}
        </Form.Item>
        {NUMBER_TYPES.has(kind) && (
          <Flex gap={12} wrap>
            <Form.Item
              label={t('custom_fields.min')}
              htmlFor="cf-min"
              validateStatus={at('validation.min') === undefined ? undefined : 'error'}
              help={at('validation.min')}
            >
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
            <Form.Item
              label={t('custom_fields.max')}
              htmlFor="cf-max"
              validateStatus={at('validation.max') === undefined ? undefined : 'error'}
              help={at('validation.max')}
            >
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
            validateStatus={at('currency') === undefined ? undefined : 'error'}
            help={at('currency') ?? t('custom_fields.currency_help')}
          >
            <Input
              id="cf-currency"
              dir="ltr"
              count={lengthLimit(3)}
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
            <Form.Item
              label={t('custom_fields.min_length')}
              htmlFor="cf-min-length"
              validateStatus={at('validation.min_length') === undefined ? undefined : 'error'}
              help={at('validation.min_length')}
            >
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
            <Form.Item
              label={t('custom_fields.max_length')}
              htmlFor="cf-max-length"
              validateStatus={at('validation.max_length') === undefined ? undefined : 'error'}
              help={at('validation.max_length')}
            >
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
            validateStatus={at('validation.pattern') === undefined ? undefined : 'error'}
            help={at('validation.pattern') ?? t('custom_fields.pattern_help')}
          >
            <Input
              id="cf-pattern"
              dir="ltr"
              count={lengthLimit(200)}
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
            validateStatus={at('default') === undefined ? undefined : 'error'}
            help={at('default') ?? t('custom_fields.default_help')}
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
      <ConflictDialog
        open={conflict !== null}
        error={conflict}
        fieldLabel={(name) => t(`custom_fields.part.${name}`)}
        opened={fieldView(base)}
        latest={fieldView(field)}
        onReload={() => {
          // Theirs: start again from the field as it is saved now.
          setConflict(null);
          setDraft(draftOf(field));
          setBase(field);
        }}
        onKeepMine={() => {
          // Mine: my values saved over theirs, knowingly.
          setConflict(null);
          setBase(field);
          if (field !== null) save(field.version);
        }}
      />
    </Drawer>
  );
}

/** The choices of a pick list: names per language; a removed choice stays, retired. */
function ChoicesEditor({
  value,
  onChange,
  problem,
}: {
  value: CustomFieldChoice[];
  onChange: (next: CustomFieldChoice[]) => void;
  problem?: string;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const [adding, setAdding] = useState<Labels | null>(null);
  const update = (index: number, patch: Partial<CustomFieldChoice>) => {
    onChange(value.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  };
  const move = (index: number, by: -1 | 1) => {
    const next = [...value];
    const [moved] = next.splice(index, 1);
    if (moved === undefined) return;
    next.splice(index + by, 0, moved);
    onChange(next);
  };
  const add = () => {
    if (adding === null || (adding.en ?? '').trim() === '') return;
    onChange([...value, { code: null, labels: cleanLabels(adding) ?? {}, retired: false }]);
    setAdding(null);
  };
  return (
    <Form.Item
      label={t('custom_fields.choices')}
      required
      validateStatus={problem === undefined ? undefined : 'error'}
      help={problem}
    >
      <Flex vertical gap={6} data-testid="cf-choices">
        {value.length > 0 && (
          // Column names, visible (QA C2): the inputs below have the same order.
          <Flex gap={6} aria-hidden data-testid="cf-choice-columns">
            <Typography.Text type="secondary" style={{ flex: '1 1 160px' }}>
              {t('settings.name_in.en')}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ flex: '1 1 120px' }}>
              {t('settings.name_in.ar')}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ flex: '1 1 120px' }}>
              {t('settings.name_in.ur')}
            </Typography.Text>
            <span style={{ width: 160 }} />
          </Flex>
        )}
        {value.map((choice, index) => (
          <Flex key={choice.code ?? `new-${String(index)}`} gap={6} align="center" wrap>
            <Input
              aria-label={t('settings.name_in.en')}
              dir="ltr"
              lang="en"
              count={lengthLimit(120)}
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
              count={lengthLimit(120)}
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
              count={lengthLimit(120)}
              style={{ flex: '1 1 120px' }}
              value={choice.labels.ur ?? ''}
              onChange={(event) => {
                update(index, { labels: { ...choice.labels, ur: event.target.value } });
              }}
              data-testid={`cf-choice-ur-${String(index)}`}
            />
            <Button
              size="small"
              icon={<ArrowUpOutlined />}
              disabled={index === 0}
              aria-label={t('settings.move_up', { name: localized(choice.labels, locale) })}
              onClick={() => {
                move(index, -1);
              }}
              data-testid={`cf-choice-up-${String(index)}`}
            />
            <Button
              size="small"
              icon={<ArrowDownOutlined />}
              disabled={index === value.length - 1}
              aria-label={t('settings.move_down', { name: localized(choice.labels, locale) })}
              onClick={() => {
                move(index, 1);
              }}
              data-testid={`cf-choice-down-${String(index)}`}
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
            onOk={add}
            destroyOnHidden
            data-testid="cf-choice-dialog"
          >
            {/* Enter adds the choice, as in any one-line form (QA C1). */}
            <div
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  add();
                }
              }}
            >
              <Form layout="vertical" component="div">
                <LabelsFields value={adding} onChange={setAdding} testId="cf-choice-name" />
              </Form>
            </div>
          </Modal>
        )}
        {value.length > 0 && (
          // Each name isolated (QA C4), joined the way the UI language lists things: the
          // list's own parts, so every name keeps its own <bdi> (never a hand-joined ", ").
          <Typography.Text type="secondary" data-testid="cf-choices-offered">
            {t('custom_fields.choices_offered')}{' '}
            {new Intl.ListFormat(locale, { type: 'unit' })
              .formatToParts(
                value.filter((c) => !c.retired).map((c) => localized(c.labels, locale)),
              )
              .map((part, i) =>
                part.type === 'element' ? (
                  <bdi key={i}>{part.value}</bdi>
                ) : (
                  <Fragment key={i}>{part.value}</Fragment>
                ),
              )}
          </Typography.Text>
        )}
      </Flex>
    </Form.Item>
  );
}

// Tone tags keep at least 4.5:1 contrast in every theme (QA BUG-07; checked in tones.test.tsx).
const INDEX_TONES: Record<CustomField['index_state'], Tone> = {
  none: 'default',
  pending: 'warning',
  building: 'info',
  active: 'success',
  failed: 'error',
};

/** Where a field's index is (D-088), live; a failure says why on hover. */
function IndexTag({ field, testId }: { field: CustomField; testId: string }) {
  const t = useLabel();
  const tag = (
    <ToneTag tone={INDEX_TONES[field.index_state]} testId={testId}>
      {t(`custom_field_index_state.${field.index_state}`)}
    </ToneTag>
  );
  if (field.index_state !== 'failed') return tag;
  return (
    <Tooltip title={t(`custom_field_index_error.${field.index_error ?? 'unexpected'}`)}>
      <span>{tag}</span>
    </Tooltip>
  );
}
