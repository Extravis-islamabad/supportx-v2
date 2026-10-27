import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Col,
  Flex,
  Form,
  Input,
  Modal,
  Radio,
  Row,
  Segmented,
  Select,
  Space,
  Typography,
} from 'antd';
import { useEffect, useMemo, useRef, useState, type ReactElement } from 'react';
import { useNavigate } from 'react-router';

import {
  ApiError,
  useCreateIncident,
  useCustomFields,
  useIncidentCatalogue,
  useIncidentCategories,
  useIncidentTemplates,
  useSession,
  useSetFormDensity,
  useUnits,
  type CustomField,
  type FormDensity,
  type IncidentCatalogue,
  type IncidentCategory,
  type IncidentTemplate,
  type TemplateField,
} from '@supportx/api-client';
import { applyServerErrors, FormField, useForm, zodResolver } from '@supportx/forms';
import {
  NoAccess,
  reportError,
  RichTextField,
  useAccess,
  useAppearance,
  useLabel,
  WriteButton,
  lengthLimit,
} from '@supportx/ui';

import { CustomFormField } from '../customFields/fields';
import { fieldName } from '../customFields/values';
import { HandOverWarning } from './assign';
import { CategoryCascade } from './CategoryCascade';
import {
  bodyOf,
  EMPTY,
  FIELDS,
  hasValue,
  IMPACT_DETAILS_MAX,
  previewPriority,
  schema,
  SUBJECT_MAX,
  type Values,
} from './form';
import { listValueLabel, scaleLabel, templateLabel } from './labels';
import { DepartmentPicker, GroupPicker, SitePicker, TechnicianPicker, UserPicker } from './pickers';
import { PriorityTag } from './tags';
import { TagsInput } from './TagsInput';

const IMPACTS = ['one_person', 'team', 'department_or_site', 'organisation'] as const;
const URGENCIES = ['low', 'medium', 'high', 'critical'] as const;
const PRIORITIES = ['p1', 'p2', 'p3', 'p4'] as const;
// Template fields, in the order the form shows them (subject and requester are always there).
const TEMPLATE_FIELDS: readonly (TemplateField & keyof Values)[] = [
  'on_behalf_of_id',
  'channel',
  'site_id',
  'department_id',
  'level',
  'category_id',
  'group_id',
  'technician_id',
  'impact',
  'urgency',
  'impact_details',
  'description',
  'tags',
];
const FULL_WIDTH = new Set<string>([
  'subject',
  'category_id',
  'impact_details',
  'description',
  'tags',
]);

type Rules = IncidentTemplate['fields'];

/**
 * The values a template starts the form with: its own defaults, else the tenant's default
 * impact and urgency (D-075), else empty. A default category retired since the template was
 * saved is left out, and `dropped` says so (nothing silently different).
 */
function startOf(
  template: IncidentTemplate | undefined,
  catalogue: IncidentCatalogue | undefined,
  categories: readonly IncidentCategory[],
): { values: Partial<Values>; dropped: string[] } {
  const defaults = (template?.defaults ?? {}) as Partial<Record<keyof Values, unknown>>;
  const values: Partial<Values> = {
    impact: (defaults.impact as string | undefined) ?? catalogue?.default_impact ?? null,
    urgency: (defaults.urgency as string | undefined) ?? catalogue?.default_urgency ?? null,
  };
  const dropped: string[] = [];
  for (const name of [...TEMPLATE_FIELDS, 'subject'] as const) {
    if (name === 'impact' || name === 'urgency') continue;
    const value = defaults[name];
    if (value === undefined || value === null) {
      (values as Record<string, unknown>)[name] = EMPTY[name];
      continue;
    }
    if (name === 'category_id') {
      let node = categories.find((n) => n.id === value);
      if (node === undefined || node.disabled) {
        // The nearest category above it still in use, else none; either way, said (QA C9).
        while (node?.disabled === true) {
          const parent = node.parent_id;
          node = parent === null ? undefined : categories.find((n) => n.id === parent);
        }
        values.category_id = node?.id ?? null;
        dropped.push(name);
        continue;
      }
    }
    if (name === 'level') {
      const level = catalogue?.levels.find((v) => v.code === value);
      if (level === undefined || level.disabled) {
        values.level = null;
        dropped.push(name);
        continue;
      }
    }
    (values as Record<string, unknown>)[name] = value;
  }
  return { values, dropped };
}

/**
 * Log an incident (REQ-INC-017). The template picker at the top chooses which fields show,
 * which are required and what they start with (REQ-INC-035); switching templates keeps what
 * was typed and asks before clearing anything the new template hides. Fields a template hides
 * are listed, never silently gone. One Idempotency-Key per form, so a double click or a retry
 * creates one incident (REQ-WI-008). Priority is shown live from the matrix (REQ-INC-009/010).
 * The layout follows the user's form density: comfortable (labels above) or compact (two
 * columns, labels on the left).
 */
export function NewIncidentPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const { can } = useAccess();
  const session = useSession();
  const userId = session.data?.user.id ?? '';
  const density: FormDensity = session.data?.user.form_density ?? 'comfortable';
  const setDensity = useSetFormDensity(userId);
  const create = useCreateIncident();
  const catalogue = useIncidentCatalogue();
  const categories = useIncidentCategories();
  const templates = useIncidentTemplates();
  const customFields = useCustomFields('incident');
  const groups = useUnits('groups');
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: EMPTY });
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [another, setAnother] = useState(false);
  const [keepRequester, setKeepRequester] = useState(false);
  const [handover, setHandover] = useState<Values | null>(null);
  const [chosenId, setChosenId] = useState<string | null>(null);
  const [switching, setSwitching] = useState<{ next: IncidentTemplate; lost: string[] } | null>(
    null,
  );
  const [dropped, setDropped] = useState<string[]>([]);
  const offered = useMemo(
    () => (templates.data ?? []).filter((x) => !x.disabled),
    [templates.data],
  );
  const fallback = offered.find((x) => x.is_default) ?? offered[0];
  // A template disabled while the form is open: keep it until the user picks another (the
  // server refuses it on save and says so), rather than switching fields under their hands.
  const template =
    (templates.data ?? []).find((x) => x.id === chosenId) ??
    (chosenId === null ? fallback : undefined);
  const rules: Rules | undefined = template?.fields;
  const shown = (name: TemplateField) => rules?.[name]?.shown ?? true;
  const required = (name: TemplateField) => rules?.[name]?.required ?? false;
  const impact = form.watch('impact');
  const urgency = form.watch('urgency');
  const group = form.watch('group_id');
  const manual = form.watch('priority');
  const preview = previewPriority(catalogue.data, impact, urgency);
  const canAssign = can('incidents.assign');
  const canPriority = can('incidents.change_priority');
  // Custom fields (WP-026): shown unless the template hides them; required by the template or
  // by the field itself; retired ones are never offered on a new incident.
  const offeredCustom = (customFields.data ?? []).filter((f) => !f.retired);
  const byKey = new Map((customFields.data ?? []).map((f) => [f.key, f]));
  const customRule = (key: string) => template?.custom_fields[key];
  const customShown = (f: CustomField) => customRule(f.key)?.shown ?? true;
  const customRequired = (f: CustomField) =>
    (customRule(f.key)?.required ?? false) || f.validation.required;
  const shownCustom = offeredCustom.filter(customShown);
  const fieldLabel = (name: string) => {
    if (!name.startsWith('custom.')) return t(`work_item.field.${name}`);
    const found = byKey.get(name.slice('custom.'.length));
    return found === undefined ? t('custom_fields.unknown_field') : fieldName(found, locale);
  };

  // What the current template filled in: a field still holding that value was not typed by
  // the user, so another template may replace it; anything else is the user's and stays.
  const started = useRef<Partial<Values>>({});
  const startedOf = (name: keyof Values): unknown =>
    name in started.current ? started.current[name] : EMPTY[name];
  const typed = (name: keyof Values, value: unknown) =>
    JSON.stringify(value) !== JSON.stringify(startedOf(name));
  const apply = (
    next: IncidentTemplate | undefined,
    clear: readonly string[] = [],
    switched = false,
  ) => {
    const start = startOf(next, catalogue.data, categories.data ?? []);
    for (const name of clear) {
      if (name.startsWith('custom.')) continue; // applyCustom clears those
      form.setValue(name as keyof Values, EMPTY[name as keyof Values]);
    }
    for (const [name, value] of Object.entries(start.values)) {
      const field = name as keyof Values;
      const current: unknown = form.getValues(field);
      if (clear.includes(name) || !typed(field, current)) {
        form.setValue(field, value);
      }
    }
    applyCustom(next, clear);
    started.current = start.values;
    // A new template brings new rules: its own check runs on save. Loading the first one never
    // wipes a message the user is already looking at.
    if (switched) form.clearErrors();
    setDropped(start.dropped);
  };
  // Custom fields start from the template's value, else the field's default. A value the user
  // typed stays, as for the other fields.
  const startedCustom = useRef<Record<string, unknown>>({});
  const applyCustom = (next: IncidentTemplate | undefined, clear: readonly string[] = []) => {
    const defaults = (next?.defaults ?? {}) as Record<string, unknown>;
    const values = { ...form.getValues('custom') };
    const starts: Record<string, unknown> = {};
    for (const f of offeredCustom) {
      const start = defaults[`custom.${f.key}`] ?? f.default ?? null;
      starts[f.key] = start;
      const before = startedCustom.current[f.key] ?? null;
      const untouched = JSON.stringify(values[f.key] ?? null) === JSON.stringify(before);
      if (clear.includes(`custom.${f.key}`)) values[f.key] = null;
      if (untouched || clear.includes(`custom.${f.key}`)) values[f.key] = start;
    }
    startedCustom.current = starts;
    form.setValue('custom', values);
  };
  // First load: apply the default template once the template, catalogue and tree are known.
  const applied = useRef<string | null>(null);
  const ready =
    template !== undefined && catalogue.data !== undefined && categories.data !== undefined;
  useEffect(() => {
    if (!ready || applied.current === template.id) return;
    const switched = applied.current !== null;
    applied.current = template.id;
    apply(template, [], switched);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs when the template changes only
  }, [ready, template?.id]);
  // Fields added or changed by an admin while the form is open (live): start values follow.
  useEffect(() => {
    if (customFields.data !== undefined && applied.current !== null) applyCustom(template);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the field list is the trigger
  }, [customFields.data]);

  if (!can('incidents.create')) return <NoAccess titleKey="nav.incidents" />;

  const choose = (id: string) => {
    const next = offered.find((x) => x.id === id);
    if (next === undefined || next.id === template?.id) return;
    // Filled-in fields the new template does not show would be lost: ask first.
    const values = form.getValues();
    const lost: string[] = TEMPLATE_FIELDS.filter(
      (name) =>
        next.fields[name]?.shown === false && typed(name, values[name]) && hasValue(values[name]),
    );
    for (const f of shownCustom) {
      const value = values.custom[f.key];
      const typedCustom =
        JSON.stringify(value ?? null) !== JSON.stringify(startedCustom.current[f.key] ?? null);
      if (next.custom_fields[f.key]?.shown === false && typedCustom && hasValue(value)) {
        lost.push(`custom.${f.key}`);
      }
    }
    if (lost.length > 0) {
      setSwitching({ next, lost });
      return;
    }
    setChosenId(next.id);
  };

  // Fields drawn on this screen: a server error on any other field is reported, never hidden.
  const rendered = new Set<string>([
    'subject',
    'requester_id',
    'priority',
    'priority_reason',
    ...TEMPLATE_FIELDS.filter(
      (name) => shown(name) && (canAssign || (name !== 'group_id' && name !== 'technician_id')),
    ),
    ...shownCustom.map((f) => `custom.${f.key}`),
  ]);
  const send = (values: Values, confirm: boolean, keepFollowing?: boolean) => {
    const body = {
      ...bodyOf(
        values,
        confirm,
        template?.id ?? null,
        shownCustom.map((f) => f.key),
      ),
      keep_following: keepFollowing ?? null,
    };
    const variant = keepFollowing === undefined ? '' : `-${String(keepFollowing)}`;
    create.mutate(
      { body, key: confirm ? `${key}-confirmed${variant}` : key },
      {
        onSuccess: (saved) => {
          setHandover(null);
          void message.success(t('incidents.created', { id: saved.display_id }));
          if (!saved.visible) {
            void navigate('/incidents', { replace: true });
            return;
          }
          if (another) {
            const requester = keepRequester ? values.requester_id : null;
            form.reset({ ...EMPTY, requester_id: requester });
            started.current = {};
            apply(template);
            setKey(crypto.randomUUID());
            // The next call starts at the top, typing into the subject (QA BUG-17).
            window.scrollTo({ top: 0, behavior: 'smooth' });
            setTimeout(() => {
              form.setFocus('subject');
            }, 0);
            return;
          }
          void navigate(`/incidents/${saved.id}`, { replace: true });
        },
        onError: (error) => {
          if (error instanceof ApiError && error.code === 'would_lose_access') {
            setHandover(values);
            return;
          }
          setKey(crypto.randomUUID()); // corrected input is a new request
          const visible = [...FIELDS, ...shownCustom.map((f) => `custom.${f.key}` as const)].filter(
            (name) => rendered.has(name),
          );
          const unseen =
            error instanceof ApiError &&
            error.fieldErrors.some((e) => !rendered.has(e.field.replace(/^body\./, '')));
          if (unseen || !applyServerErrors(error, form.setError, visible)) reportError(error);
        },
      },
    );
  };
  // The template's required fields, checked with the form's own rules so every missing field
  // is marked in one go (whether or not the rest of the form is valid).
  const missingRequired = () => {
    const values = form.getValues();
    const missing = TEMPLATE_FIELDS.filter(
      (name) => required(name) && rendered.has(name) && !hasValue(values[name]),
    );
    for (const name of missing) form.setError(name, { message: 'errors.field.required' });
    const missingCustom = shownCustom.filter(
      (f) => customRequired(f) && !hasValue(values.custom[f.key]),
    );
    for (const f of missingCustom) {
      form.setError(`custom.${f.key}`, { message: 'errors.field.required' });
    }
    return [...missing, ...missingCustom.map((f) => `custom.${f.key}`)];
  };
  const save = () =>
    form.handleSubmit(
      (values) => {
        if (missingRequired().length > 0) return;
        send(values, false);
      },
      () => {
        missingRequired();
      },
    )();
  const control = form.control;
  const compact = density === 'compact';
  const groupName =
    groups.data?.find((g) => g.id === handover?.group_id)?.name ?? t('incidents.no_group');
  const hidden: string[] = [
    ...TEMPLATE_FIELDS.filter((name) => !shown(name)),
    ...offeredCustom.filter((f) => !customShown(f)).map((f) => `custom.${f.key}`),
  ];
  const span = (name: string, comfortable: number) =>
    FULL_WIDTH.has(name) ? 24 : compact ? 12 : comfortable;

  const cell = (name: TemplateField, comfortable: number, element: ReactElement) =>
    shown(name) ? (
      <Col key={name} xs={24} md={span(name, comfortable)}>
        {element}
      </Col>
    ) : null;

  interface TemplateOption {
    value: string;
    label: string;
  }
  const templateOptions = ((): (
    TemplateOption | { label: string; options: TemplateOption[] }
  )[] => {
    const grouped = new Map<string, { value: string; label: string }[]>();
    for (const x of offered) {
      const groupLabel = x.group_name ?? '';
      const list = grouped.get(groupLabel) ?? [];
      list.push({ value: x.id, label: templateLabel(t, x, locale) });
      grouped.set(groupLabel, list);
    }
    // Headings only when some template has a group; the others then sit under "Without a
    // group", never under a heading that repeats the field's name (QA C4).
    if (grouped.size === 1 && grouped.has('')) return grouped.get('') ?? [];
    return [...grouped.entries()].map(([name, options]) =>
      name === '' ? { label: t('templates.ungrouped'), options } : { label: name, options },
    );
  })();

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Flex justify="space-between" align="center" wrap gap={8}>
        <Typography.Title level={1} style={{ margin: 0 }}>
          {t('incidents.new')}
        </Typography.Title>
        <Segmented<FormDensity>
          aria-label={t('form_density.title')}
          value={density}
          onChange={(next) => {
            setDensity.mutate(next, {
              onError: (error) => {
                reportError(error);
              },
            });
          }}
          options={[
            { value: 'comfortable', label: t('form_density.comfortable') },
            { value: 'compact', label: t('form_density.compact') },
          ]}
          data-testid="inc-density"
        />
      </Flex>
      <Card>
        <Form
          layout={compact ? 'horizontal' : 'vertical'}
          labelCol={compact ? { flex: '150px' } : undefined}
          wrapperCol={compact ? { flex: 1 } : undefined}
          labelWrap
          labelAlign="left"
          colon={false}
          component="div"
          data-testid="inc-form"
          data-density={density}
        >
          <Form.Item label={t('templates.field')} htmlFor="inc-template-picker">
            <Select
              id="inc-template-picker"
              showSearch
              optionFilterProp="label"
              loading={templates.isLoading}
              value={template?.id}
              onChange={choose}
              options={templateOptions}
              notFoundContent={t('templates.none_found')}
              data-testid="inc-template"
            />
          </Form.Item>
          {template !== undefined && template.disabled && (
            <Alert
              type="warning"
              showIcon
              role="status"
              style={{ marginBottom: 16 }}
              message={t('templates.disabled_meanwhile')}
              data-testid="inc-template-disabled"
            />
          )}
          {templates.isError && (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 16 }}
              message={t('templates.load_failed')}
              data-testid="inc-template-error"
            />
          )}
          {hidden.length > 0 && (
            <Alert
              type="info"
              showIcon
              role="status"
              style={{ marginBottom: 16 }}
              message={t('templates.hidden_fields', {
                fields: hidden.map(fieldLabel).join(t('list.separator')),
              })}
              data-testid="inc-hidden-fields"
            />
          )}
          {dropped.length > 0 && (
            <Alert
              type="warning"
              showIcon
              role="status"
              style={{ marginBottom: 16 }}
              message={t('templates.default_retired', {
                fields: dropped.map(fieldLabel).join(t('list.separator')),
              })}
              data-testid="inc-dropped-defaults"
            />
          )}
          <Typography.Paragraph type="secondary" data-testid="inc-required-note">
            {t('incidents.required_note')}
          </Typography.Paragraph>
          <Row gutter={16}>
            <Col xs={24}>
              <FormField
                control={control}
                name="subject"
                labelKey="work_item.field.subject"
                required
                render={(field) => (
                  <Input
                    {...field}
                    dir="auto"
                    count={lengthLimit(SUBJECT_MAX, true)}
                    data-testid="inc-subject"
                  />
                )}
              />
            </Col>
            <Col xs={24} md={12}>
              <FormField
                control={control}
                name="requester_id"
                labelKey="work_item.field.requester_id"
                required
                render={(field) => (
                  <UserPicker
                    id={field.id}
                    value={field.value}
                    onChange={field.onChange}
                    testId="inc-requester"
                    ariaLabel={t('work_item.field.requester_id')}
                  />
                )}
              />
            </Col>
            {cell(
              'on_behalf_of_id',
              12,
              <FormField
                control={control}
                name="on_behalf_of_id"
                labelKey="work_item.field.on_behalf_of_id"
                required={required('on_behalf_of_id')}
                render={(field) => (
                  <UserPicker
                    id={field.id}
                    value={field.value}
                    onChange={field.onChange}
                    testId="inc-on-behalf"
                    ariaLabel={t('work_item.field.on_behalf_of_id')}
                  />
                )}
              />,
            )}
            {cell(
              'channel',
              8,
              <FormField
                control={control}
                name="channel"
                labelKey="work_item.field.channel"
                required={required('channel')}
                render={(field) => (
                  <Radio.Group
                    id={field.id}
                    value={field.value}
                    onChange={(event) => {
                      field.onChange(event.target.value);
                    }}
                    optionType="button"
                    options={[
                      { value: 'phone', label: t('work_item_channel.phone') },
                      { value: 'walk_up', label: t('work_item_channel.walk_up') },
                    ]}
                    data-testid="inc-channel"
                  />
                )}
              />,
            )}
            {cell(
              'site_id',
              8,
              <FormField
                control={control}
                name="site_id"
                labelKey="work_item.field.site_id"
                helpKey="incidents.site_help"
                required={required('site_id')}
                render={(field) => (
                  <SitePicker
                    id={field.id}
                    value={field.value}
                    onChange={field.onChange}
                    testId="inc-site"
                    ariaLabel={t('work_item.field.site_id')}
                  />
                )}
              />,
            )}
            {cell(
              'department_id',
              8,
              <FormField
                control={control}
                name="department_id"
                labelKey="work_item.field.department_id"
                helpKey="incidents.department_help"
                required={required('department_id')}
                render={(field) => (
                  <DepartmentPicker
                    id={field.id}
                    value={field.value}
                    onChange={field.onChange}
                    testId="inc-department"
                    ariaLabel={t('work_item.field.department_id')}
                  />
                )}
              />,
            )}
            {cell(
              'level',
              8,
              <FormField
                control={control}
                name="level"
                labelKey="work_item.field.level"
                required={required('level')}
                render={(field) => (
                  <Select
                    id={field.id}
                    allowClear
                    value={field.value ?? undefined}
                    onChange={(next: string | undefined) => {
                      field.onChange(next ?? null);
                    }}
                    options={(catalogue.data?.levels ?? [])
                      .filter((v) => !v.disabled)
                      .map((v) => ({
                        value: v.code,
                        label: listValueLabel(t, 'level', v, locale),
                      }))}
                    data-testid="inc-level"
                  />
                )}
              />,
            )}
            {cell(
              'category_id',
              24,
              <FormField
                control={control}
                name="category_id"
                labelKey="work_item.field.category_id"
                required={required('category_id')}
                render={(field) => (
                  <CategoryCascade
                    id={field.id}
                    value={field.value}
                    onChange={field.onChange}
                    testId="inc-category"
                  />
                )}
              />,
            )}
            {canAssign &&
              cell(
                'group_id',
                12,
                <FormField
                  control={control}
                  name="group_id"
                  labelKey="work_item.field.group_id"
                  required={required('group_id')}
                  render={(field) => (
                    <GroupPicker
                      id={field.id}
                      value={field.value}
                      onChange={(next) => {
                        field.onChange(next);
                        form.setValue('technician_id', null);
                      }}
                      testId="inc-group"
                      ariaLabel={t('work_item.field.group_id')}
                    />
                  )}
                />,
              )}
            {canAssign &&
              cell(
                'technician_id',
                12,
                <FormField
                  control={control}
                  name="technician_id"
                  labelKey="work_item.field.technician_id"
                  required={required('technician_id')}
                  render={(field) => (
                    <TechnicianPicker
                      id={field.id}
                      groupId={group}
                      value={field.value}
                      onChange={field.onChange}
                      testId="inc-technician"
                      ariaLabel={t('work_item.field.technician_id')}
                    />
                  )}
                />,
              )}
            {cell(
              'impact',
              8,
              <FormField
                control={control}
                name="impact"
                labelKey="work_item.field.impact"
                required={required('impact')}
                render={(field) => (
                  <Select
                    id={field.id}
                    allowClear
                    value={field.value ?? undefined}
                    onChange={(next: string | undefined) => {
                      field.onChange(next ?? null);
                    }}
                    options={IMPACTS.map((v) => ({
                      value: v,
                      label: scaleLabel(t, catalogue.data, 'impact', v, locale),
                    }))}
                    data-testid="inc-impact"
                  />
                )}
              />,
            )}
            {cell(
              'urgency',
              8,
              <FormField
                control={control}
                name="urgency"
                labelKey="work_item.field.urgency"
                required={required('urgency')}
                render={(field) => (
                  <Select
                    id={field.id}
                    allowClear
                    value={field.value ?? undefined}
                    onChange={(next: string | undefined) => {
                      field.onChange(next ?? null);
                    }}
                    options={URGENCIES.map((v) => ({
                      value: v,
                      label: scaleLabel(t, catalogue.data, 'urgency', v, locale),
                    }))}
                    data-testid="inc-urgency"
                  />
                )}
              />,
            )}
            <Col xs={24} md={compact ? 12 : 8}>
              <Form.Item label={t('work_item.field.priority')}>
                <Space direction="vertical" style={{ width: '100%' }}>
                  <span data-testid="inc-priority-preview">
                    {manual === null &&
                      (preview === null ? (
                        <Typography.Text type="secondary">
                          {t('incidents.priority_pending')}
                        </Typography.Text>
                      ) : (
                        <PriorityTag priority={preview.priority as 'p1'} source={preview.source} />
                      ))}
                  </span>
                  {canPriority && (
                    <Select
                      aria-label={t('incidents.priority_override')}
                      value={manual ?? ''}
                      onChange={(next: string) => {
                        form.setValue('priority', next === '' ? null : next);
                      }}
                      options={[
                        { value: '', label: t('incidents.priority_from_matrix') },
                        ...PRIORITIES.map((p) => ({
                          value: p,
                          label: scaleLabel(t, catalogue.data, 'priority', p, locale),
                        })),
                      ]}
                      data-testid="inc-priority-override"
                    />
                  )}
                </Space>
              </Form.Item>
            </Col>
            {manual !== null && (
              <Col xs={24}>
                <FormField
                  control={control}
                  name="priority_reason"
                  labelKey="work_item.field.priority_reason"
                  required
                  render={(field) => (
                    <Input
                      {...field}
                      dir="auto"
                      count={lengthLimit(500)}
                      data-testid="inc-priority-reason"
                    />
                  )}
                />
              </Col>
            )}
            {cell(
              'impact_details',
              24,
              <FormField
                control={control}
                name="impact_details"
                labelKey="work_item.field.impact_details"
                helpKey="incidents.impact_details_help"
                required={required('impact_details')}
                render={(field) => (
                  <Input.TextArea
                    {...field}
                    dir="auto"
                    autoSize={{ minRows: 2, maxRows: 6 }}
                    count={lengthLimit(IMPACT_DETAILS_MAX, true)}
                    data-testid="inc-impact-details"
                  />
                )}
              />,
            )}
            {cell(
              'description',
              24,
              <FormField
                control={control}
                name="description"
                labelKey="work_item.field.description"
                required={required('description')}
                render={(field) => (
                  <RichTextField
                    id={field.id}
                    label={t('work_item.field.description')}
                    value={field.value}
                    onChange={field.onChange}
                    testId="inc-description-editor"
                  />
                )}
              />,
            )}
            {cell(
              'tags',
              24,
              <FormField
                control={control}
                name="tags"
                labelKey="work_item.field.tags"
                required={required('tags')}
                render={(field) => (
                  <TagsInput
                    id={field.id}
                    value={field.value}
                    onChange={field.onChange}
                    testId="inc-tags"
                  />
                )}
              />,
            )}
            {shownCustom.map((f) => (
              <Col key={f.key} xs={24} md={f.field_type === 'long_text' ? 24 : 12}>
                <CustomFormField control={control} field={f} required={customRequired(f)} />
              </Col>
            ))}
          </Row>
          <Space wrap>
            <WriteButton
              type="primary"
              loading={create.isPending}
              // Never a silent dead button: before the templates load, the server applies the
              // default template and its rules, and any refusal is shown.
              disabled={create.isPending}
              onClick={() => void save()}
              data-testid="inc-save"
            >
              {t('incidents.save')}
            </WriteButton>
            <Button onClick={() => void navigate('/incidents')}>{t('actions.cancel')}</Button>
            <Checkbox
              checked={another}
              onChange={(event) => {
                setAnother(event.target.checked);
              }}
              data-testid="inc-another"
            >
              {t('incidents.create_another')}
            </Checkbox>
            {another && (
              <Checkbox
                checked={keepRequester}
                onChange={(event) => {
                  setKeepRequester(event.target.checked);
                }}
                data-testid="inc-keep-requester"
              >
                {t('incidents.keep_requester')}
              </Checkbox>
            )}
          </Space>
        </Form>
      </Card>
      <Modal
        open={switching !== null}
        title={t('templates.switch_title', {
          name: switching === null ? '' : templateLabel(t, switching.next, locale),
        })}
        okText={t('templates.switch_confirm')}
        cancelText={t('templates.switch_keep')}
        onCancel={() => {
          setSwitching(null);
        }}
        onOk={() => {
          if (switching === null) return;
          apply(switching.next, switching.lost, true);
          applied.current = switching.next.id;
          setChosenId(switching.next.id);
          setSwitching(null);
        }}
        data-testid="inc-template-switch"
      >
        <Typography.Paragraph>
          {t('templates.switch_body', {
            fields: (switching?.lost ?? []).map(fieldLabel).join(t('list.separator')),
          })}
        </Typography.Paragraph>
      </Modal>
      <HandOverWarning
        open={handover !== null}
        displayId={t('incidents.this_incident')}
        group={groupName}
        pending={create.isPending}
        onCancel={() => {
          setHandover(null);
        }}
        onConfirm={(keepFollowing) => {
          if (handover !== null) send(handover, true, keepFollowing);
        }}
      />
    </Space>
  );
}
