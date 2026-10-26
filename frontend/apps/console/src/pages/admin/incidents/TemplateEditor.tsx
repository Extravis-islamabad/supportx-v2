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
  useIncidentCatalogue,
  useIncidentTemplateChange,
  type FieldRule,
  type IncidentTemplate,
  type Labels,
  type TemplateField,
} from '@supportx/api-client';
import { reportError, RichTextField, useAppearance, useLabel, WriteButton } from '@supportx/ui';

import { CategoryCascade } from '../../incidents/CategoryCascade';
import { listValueLabel, scaleLabel, templateLabel } from '../../incidents/labels';
import { GroupPicker, SitePicker } from '../../incidents/pickers';
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
type Rules = Record<TemplateField, FieldRule>;
type Defaults = Partial<Record<TemplateField, unknown>>;
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
  ) as Rules;
}

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
  const change = useIncidentTemplateChange();
  const [names, setNames] = useState<Labels>(template?.labels ?? {});
  const [description, setDescription] = useState(template?.description ?? '');
  const [group, setGroup] = useState(template?.group_name ?? '');
  const [forRequesters, setForRequesters] = useState(template?.for_requesters ?? false);
  const [rules, setRules] = useState<Rules>(() => ({
    ...blankRules(),
    ...((template?.fields ?? {}) as Partial<Rules>),
  }));
  const [defaults, setDefaults] = useState<Defaults>((template?.defaults ?? {}) as Defaults);
  const [problems, setProblems] = useState<string[]>([]);
  const fieldLabel = (f: TemplateField) => t(`work_item.field.${f}`);
  const setDefault = (f: TemplateField, value: unknown) => {
    setDefaults({ ...defaults, [f]: value });
  };
  const shippedName =
    template !== null && template.code !== null
      ? templateLabel(t, { ...template, labels: null }, locale)
      : null;

  const save = () => {
    setProblems([]);
    const labels = cleanLabels(names);
    const cleanDefaults = Object.fromEntries(
      Object.entries(defaults).filter(
        ([, v]) =>
          v !== null && v !== undefined && v !== '' && !(Array.isArray(v) && v.length === 0),
      ),
    );
    const body = {
      description: description.trim() === '' ? null : description.trim(),
      group_name: group.trim() === '' ? null : group.trim(),
      for_requesters: forRequesters,
      fields: rules,
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
          const found = templateProblems(t, error);
          if (found.length > 0) setProblems(found);
          else reportError(error);
        },
      },
    );
  };

  const defaultControl = (f: TemplateField) => {
    const id = `tpl-default-${f}`;
    const value = defaults[f];
    switch (f) {
      case 'subject':
        return (
          <Input
            id={id}
            dir="auto"
            maxLength={250}
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
            maxLength={2000}
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
            value={value ?? null}
            onChange={(event) => {
              setDefault(f, event.target.value);
            }}
            optionType="button"
            options={[
              { value: null, label: t('settings.no_default') },
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
          <Select
            id={id}
            mode="tags"
            value={Array.isArray(value) ? (value as string[]) : []}
            onChange={(next: string[]) => {
              setDefault(f, next);
            }}
            tokenSeparators={[',']}
            data-testid={id}
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
              maxLength={60}
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
            maxLength={500}
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
      <Table
        size="small"
        rowKey={(f: TemplateField) => f}
        pagination={false}
        dataSource={FIELDS}
        scroll={{ x: true }}
        columns={[
          {
            key: 'field',
            title: t('templates.field_name'),
            render: (_: unknown, f: TemplateField) => fieldLabel(f),
          },
          ...FLAGS.map((flag) => ({
            key: flag,
            title: t(`templates.flag.${flag}`),
            render: (_: unknown, f: TemplateField) => {
              const locked = FIXED.has(f) && (flag === 'shown' || flag === 'required');
              const control = (
                <Switch
                  size="small"
                  checked={rules[f][flag]}
                  disabled={locked}
                  aria-label={t('templates.flag_for', {
                    flag: t(`templates.flag.${flag}`),
                    field: fieldLabel(f),
                  })}
                  onChange={(on) => {
                    setRules({ ...rules, [f]: toggle(rules[f], flag, on) });
                  }}
                  data-testid={`tpl-rule-${f}-${flag}`}
                />
              );
              return locked ? (
                <Tooltip title={t('templates.always_required')}>{control}</Tooltip>
              ) : (
                control
              );
            },
          })),
        ]}
      />
      {(() => {
        const hiddenRequired = FIELDS.filter(
          (f) => !rules[f].shown && rules[f].required && defaults[f] == null,
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
        component="div"
      >
        {FIELDS.filter((f) => DEFAULTABLE.has(f)).map((f) => (
          <Form.Item key={f} label={fieldLabel(f)} htmlFor={`tpl-default-${f}`}>
            {defaultControl(f)}
          </Form.Item>
        ))}
      </Form>
    </Drawer>
  );
}
