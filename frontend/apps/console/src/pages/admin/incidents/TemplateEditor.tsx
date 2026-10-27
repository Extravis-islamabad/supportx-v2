import {
  App,
  Button,
  Drawer,
  Flex,
  Form,
  Input,
  Radio,
  Select,
  Space,
  Switch,
  Table,
  Tooltip,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useCustomFields,
  useIncidentCatalogue,
  useIncidentTemplateChange,
  type FieldRule,
  type IncidentTemplate,
  type Labels,
  type TemplateField,
} from '@supportx/api-client';
import {
  reportError,
  RichTextField,
  useAppearance,
  useLabel,
  WriteButton,
  lengthLimit,
} from '@supportx/ui';

import { CustomFieldControl } from '../../customFields/fields';
import { fieldName } from '../../customFields/values';
import { CategoryCascade } from '../../incidents/CategoryCascade';
import { listValueLabel, scaleLabel, templateLabel } from '../../incidents/labels';
import { GroupPicker, SitePicker } from '../../incidents/pickers';
import { TagsInput } from '../../incidents/TagsInput';
import { cleanLabels, templateProblems } from './helpers';
import { LabelsFields, Problems } from './shared';

const FIELDS: TemplateField[] = [
  'subject',
  'requester_id',
  'on_behalf_of_id',
  'channel',
  'site_id',
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
const FIXED = new Set<TemplateField>(['subject', 'requester_id']);
// People are never given a starting value: a default technician would assign every incident
// from the template to one person.
const DEFAULTABLE = new Set<TemplateField>([
  'subject',
  'channel',
  'site_id',
  'level',
  'category_id',
  'group_id',
  'impact',
  'urgency',
  'impact_details',
  'description',
  'tags',
]);
const IMPACTS = ['one_person', 'team', 'department_or_site', 'organisation'];
const URGENCIES = ['low', 'medium', 'high', 'critical'];
// Built-in fields by name, custom fields as `custom.<key>` (WP-026).
type Rules = Record<string, FieldRule>;
type Defaults = Record<string, unknown>;
const CUSTOM = 'custom.';
const NEW_RULE: FieldRule = {
  shown: true,
  required: false,
  requester_can_see: true,
  requester_can_fill: false,
};
type Flag = keyof FieldRule;
const FLAGS: Flag[] = ['shown', 'required', 'requester_can_see', 'requester_can_fill'];

function blankRules(): Rules {
  return Object.fromEntries(
    FIELDS.map((f) => [
      f,
      {
        shown: true,
        required: FIXED.has(f),
        requester_can_see: true,
        requester_can_fill: FIXED.has(f) || f === 'description',
      },
    ]),
  );
}

const NO_CHANNEL = 'none'; // the radio's "no default" (a radio value is never null: QA BUG-08)

/** A switch change and what it implies (hidden → not required; fill → see), never contradictory. */
function toggle(rule: FieldRule, flag: Flag, on: boolean): FieldRule {
  const next = { ...rule, [flag]: on };
  if (flag === 'required' && on) next.shown = true;
  if (flag === 'requester_can_fill' && on) next.requester_can_see = true;
  if (flag === 'requester_can_see' && !on) next.requester_can_fill = false;
  return next;
}

/**
 * Edit one template: name, group, description, whether requesters may use it in the portal,
 * and per field shown / required / requester can see / requester can fill in, plus starting
 * values. Contradictions are prevented here and refused by the server (REQ-WI-009 AC4).
 */
export function TemplateEditor({
  template,
  onClose,
}: {
  template: IncidentTemplate | null;
  onClose: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const catalogue = useIncidentCatalogue();
  const customFields = useCustomFields('incident');
  const change = useIncidentTemplateChange();
  const [names, setNames] = useState<Labels>(template?.labels ?? {});
  const [description, setDescription] = useState(template?.description ?? '');
  const [group, setGroup] = useState(template?.group_name ?? '');
  const [forRequesters, setForRequesters] = useState(template?.for_requesters ?? false);
  const [rules, setRules] = useState<Rules>(() => ({
    ...blankRules(),
    ...(template?.fields ?? {}),
    ...Object.fromEntries(
      Object.entries(template?.custom_fields ?? {}).map(([key, rule]) => [`${CUSTOM}${key}`, rule]),
    ),
  }));
  const [defaults, setDefaults] = useState<Defaults>(template?.defaults ?? {});
  const [problems, setProblems] = useState<string[]>([]);
  // Custom fields in use on new incidents (retired ones take no values) follow the built-in ones.
  const custom = (customFields.data ?? []).filter((f) => !f.retired);
  const customByName = new Map(custom.map((f) => [`${CUSTOM}${f.key}`, f]));
  const rows: string[] = [...FIELDS, ...custom.map((f) => `${CUSTOM}${f.key}`)];
  const ruleOf = (name: string): FieldRule => rules[name] ?? NEW_RULE;
  const fieldLabel = (name: string) => {
    const found = customByName.get(name);
    if (found !== undefined) return fieldName(found, locale);
    return t(`work_item.field.${name}`);
  };
  const setDefault = (f: string, value: unknown) => {
    setDefaults({ ...defaults, [f]: value });
  };
  const shippedName =
    template !== null && template.code !== null
      ? templateLabel(t, { ...template, labels: null }, locale)
      : null;

  const save = () => {
    setProblems([]);
    const labels = cleanLabels(names);
    const known = new Set(rows);
    const cleanDefaults = Object.fromEntries(
      Object.entries(defaults).filter(
        ([name, v]) =>
          known.has(name) &&
          v !== null &&
          v !== undefined &&
          v !== '' &&
          !(Array.isArray(v) && v.length === 0),
      ),
    );
    const body = {
      description: description.trim() === '' ? null : description.trim(),
      group_name: group.trim() === '' ? null : group.trim(),
      for_requesters: forRequesters,
      // Only fields that exist now: a rule left by a removed field is dropped (AC4).
      fields: Object.fromEntries(rows.map((name) => [name, ruleOf(name)])),
      defaults: cleanDefaults,
    };
    change.mutate(
      template === null
        ? { kind: 'create', body: { ...body, labels: labels ?? {} } }
        : {
            kind: 'update',
            id: template.id,
            version: template.version,
            body: { ...body, labels: labels ?? (template.code === null ? {} : null) },
          },
      {
        onSuccess: () => {
          void message.success(t('settings.saved'));
          onClose();
        },
        onError: (error) => {
          if (error instanceof ApiError && error.isConflict) {
            setProblems([t('settings.changed_elsewhere')]);
            return;
          }
          const found = templateProblems(t, error, fieldLabel);
          if (found.length > 0) setProblems(found);
          else reportError(error);
        },
      },
    );
  };

  const defaultControl = (name: string) => {
    const id = `tpl-default-${name}`;
    const value = defaults[name];
    const found = customByName.get(name);
    if (found !== undefined) {
      return (
        <CustomFieldControl
          id={id}
          field={found}
          value={value ?? null}
          onChange={(next) => {
            setDefault(name, next);
          }}
          testId={id}
          ariaLabel={fieldLabel(name)}
        />
      );
    }
    const f = name as TemplateField;
    switch (f) {
      case 'subject':
        return (
          <Input
            id={id}
            dir="auto"
            count={lengthLimit(250)}
            value={typeof value === 'string' ? value : ''}
            onChange={(event) => {
              setDefault(f, event.target.value);
            }}
            data-testid={id}
          />
        );
      case 'impact_details':
        return (
          <Input.TextArea
            id={id}
            dir="auto"
            count={lengthLimit(2000)}
            autoSize={{ minRows: 2, maxRows: 4 }}
            value={typeof value === 'string' ? value : ''}
            onChange={(event) => {
              setDefault(f, event.target.value);
            }}
            data-testid={id}
          />
        );
      case 'description':
        return (
          <RichTextField
            id={id}
            label={fieldLabel(f)}
            value={typeof value === 'string' ? value : ''}
            onChange={(html) => {
              setDefault(f, html);
            }}
            testId={id}
          />
        );
      case 'channel':
        return (
          <Radio.Group
            id={id}
            value={value ?? NO_CHANNEL}
            onChange={(event) => {
              const chosen = event.target.value as string;
              setDefault(f, chosen === NO_CHANNEL ? null : chosen);
            }}
            optionType="button"
            options={[
              { value: NO_CHANNEL, label: t('settings.no_default') },
              { value: 'phone', label: t('work_item_channel.phone') },
              { value: 'walk_up', label: t('work_item_channel.walk_up') },
            ]}
            data-testid={id}
          />
        );
      case 'site_id':
        return (
          <SitePicker
            id={id}
            value={(value as string | null | undefined) ?? null}
            onChange={(next) => {
              setDefault(f, next);
            }}
            testId={id}
            ariaLabel={fieldLabel(f)}
          />
        );
      case 'group_id':
        return (
          <GroupPicker
            id={id}
            value={(value as string | null | undefined) ?? null}
            onChange={(next) => {
              setDefault(f, next);
            }}
            testId={id}
            ariaLabel={fieldLabel(f)}
          />
        );
      case 'category_id':
        return (
          <CategoryCascade
            id={id}
            value={(value as string | null | undefined) ?? null}
            onChange={(next) => {
              setDefault(f, next);
            }}
            testId={id}
          />
        );
      case 'level':
        return (
          <Select
            id={id}
            allowClear
            value={(value as string | undefined) ?? undefined}
            onChange={(next: string | undefined) => {
              setDefault(f, next ?? null);
            }}
            options={(catalogue.data?.levels ?? [])
              .filter((v) => !v.disabled)
              .map((v) => ({ value: v.code, label: listValueLabel(t, 'level', v, locale) }))}
            data-testid={id}
          />
        );
      case 'impact':
      case 'urgency':
        return (
          <Select
            id={id}
            allowClear
            placeholder={t('settings.tenant_default')}
            value={(value as string | undefined) ?? undefined}
            onChange={(next: string | undefined) => {
              setDefault(f, next ?? null);
            }}
            options={(f === 'impact' ? IMPACTS : URGENCIES).map((code) => ({
              value: code,
              label: scaleLabel(t, catalogue.data, f, code, locale),
            }))}
            data-testid={id}
          />
        );
      case 'tags':
        return (
          <TagsInput
            id={id}
            value={Array.isArray(value) ? (value as string[]) : []}
            onChange={(next) => {
              setDefault(f, next);
            }}
            testId={id}
          />
        );
      default:
        return null;
    }
  };

  return (
    <Drawer
      open
      width={920}
      title={
        template === null
          ? t('templates.new')
          : t('templates.edit_title', { name: templateLabel(t, template, locale) })
      }
      onClose={onClose}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={onClose}>{t('actions.cancel')}</Button>
          <WriteButton
            type="primary"
            loading={change.isPending}
            onClick={save}
            data-testid="tpl-editor-save"
          >
            {t('actions.save')}
          </WriteButton>
        </Space>
      }
      data-testid="tpl-editor"
    >
      <Problems problems={problems} testId="tpl-editor-problems" />
      <Form layout="vertical" component="div">
        {shippedName !== null && (
          <Typography.Paragraph type="secondary">
            {t('settings.shipped_name_hint', { name: shippedName })}
          </Typography.Paragraph>
        )}
        <LabelsFields value={names} onChange={setNames} testId="tpl-editor-name" />
        <Flex gap={16} wrap>
          <Form.Item
            label={t('templates.group')}
            htmlFor="tpl-editor-group"
            style={{ flex: '1 1 240px' }}
          >
            <Input
              id="tpl-editor-group"
              dir="auto"
              count={lengthLimit(60)}
              value={group}
              onChange={(event) => {
                setGroup(event.target.value);
              }}
              data-testid="tpl-editor-group"
            />
          </Form.Item>
          <Form.Item
            label={t('templates.for_requesters')}
            htmlFor="tpl-editor-portal"
            help={t('templates.for_requesters_help')}
          >
            <Switch
              id="tpl-editor-portal"
              checked={forRequesters}
              onChange={setForRequesters}
              data-testid="tpl-editor-portal"
            />
          </Form.Item>
        </Flex>
        <Form.Item label={t('templates.description')} htmlFor="tpl-editor-description">
          <Input.TextArea
            id="tpl-editor-description"
            dir="auto"
            count={lengthLimit(500)}
            autoSize={{ minRows: 2, maxRows: 4 }}
            value={description}
            onChange={(event) => {
              setDescription(event.target.value);
            }}
            data-testid="tpl-editor-description"
          />
        </Form.Item>
      </Form>
      <Typography.Title level={3}>{t('templates.fields')}</Typography.Title>
      <Typography.Paragraph type="secondary">{t('templates.fields_help')}</Typography.Paragraph>
      <Typography.Paragraph type="secondary" data-testid="tpl-editor-locked-note">
        {t('templates.locked_note')}
      </Typography.Paragraph>
      <Table
        size="small"
        rowKey={(f: string) => f}
        pagination={false}
        dataSource={rows}
        scroll={{ x: true }}
        columns={[
          {
            key: 'field',
            title: t('templates.field_name'),
            render: (_: unknown, f: string) => <bdi dir="auto">{fieldLabel(f)}</bdi>,
          },
          ...FLAGS.map((flag) => ({
            key: flag,
            title: t(`templates.flag.${flag}`),
            render: (_: unknown, f: string) => {
              // Subject and requester: always shown and required, and always seen and filled
              // in by requesters, or nobody could log an incident from the portal (D-086).
              const locked = FIXED.has(f as TemplateField);
              const rule = ruleOf(f);
              const control = (
                <Switch
                  size="small"
                  checked={rule[flag]}
                  disabled={locked}
                  aria-label={t('templates.flag_for', {
                    flag: t(`templates.flag.${flag}`),
                    field: fieldLabel(f),
                  })}
                  onChange={(on) => {
                    setRules({ ...rules, [f]: toggle(rule, flag, on) });
                  }}
                  data-testid={`tpl-rule-${f}-${flag}`}
                />
              );
              return locked ? (
                <Tooltip
                  title={t(
                    flag === 'shown' || flag === 'required'
                      ? 'templates.always_required'
                      : 'templates.requester_always_needed',
                  )}
                >
                  {control}
                </Tooltip>
              ) : (
                control
              );
            },
          })),
        ]}
      />
      {(() => {
        const hiddenRequired = rows.filter(
          (f) => !ruleOf(f).shown && ruleOf(f).required && defaults[f] == null,
        );
        return hiddenRequired.length === 0 ? null : (
          <Typography.Text type="warning" role="status" data-testid="tpl-editor-hidden-required">
            {t('templates.hidden_required_hint', {
              fields: hiddenRequired.map(fieldLabel).join(t('list.separator')),
            })}
          </Typography.Text>
        );
      })()}
      <Typography.Title level={3} style={{ marginTop: 24 }}>
        {t('templates.starting_values')}
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        {t('templates.starting_values_help')}
      </Typography.Paragraph>
      <Form
        layout="horizontal"
        labelCol={{ flex: '170px' }}
        wrapperCol={{ flex: 1 }}
        labelWrap
        colon={false}
        component="div"
      >
        {rows
          .filter(
            (f) =>
              DEFAULTABLE.has(f as TemplateField) ||
              (customByName.has(f) && customByName.get(f)?.field_type !== 'person'),
          )
          .map((f) => (
            <Form.Item key={f} label={fieldLabel(f)} htmlFor={`tpl-default-${f}`}>
              {defaultControl(f)}
            </Form.Item>
          ))}
      </Form>
    </Drawer>
  );
}
