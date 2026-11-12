import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  EyeOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import {
  Button,
  Card,
  ConfigProvider,
  Flex,
  Form,
  Input,
  Modal,
  Radio,
  Segmented,
  Select,
  Space,
  Switch,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  arrangeFields,
  type FormLayout,
  type LabelPosition,
  type LayoutAudience,
  type LayoutPart,
  type LayoutSection,
} from '@supportx/forms';
import { useLabel } from '@supportx/ui';

import { LabelsFields } from './shared';

// The form designer (WP-046a S5b; REQ-INC-036): a template's create form in sections, one or two
// columns, collapsible, labels above or beside, for technicians and (optionally its own) for
// requesters. Keyboard first (D-, plan answer 3): every move is a button or a choice, so it works
// without a pointer; drag to reorder is a later item. A layout only arranges: which fields are
// shown or required stays in the field table above, and a field no section names goes last.

const newId = (): string => `s_${Math.random().toString(36).slice(2, 10)}`;

function blankPart(fields: readonly string[]): LayoutPart {
  return { label_position: 'top', sections: [{ id: newId(), names: {}, fields: [...fields] }] };
}

function move<T>(list: readonly T[], from: number, to: number): T[] {
  const next = [...list];
  const [item] = next.splice(from, 1);
  if (item !== undefined) next.splice(to, 0, item);
  return next;
}

export function FormLayoutDesigner({
  value,
  onChange,
  fields,
  requesterFields,
  fieldLabel,
}: {
  value: FormLayout | null;
  onChange: (next: FormLayout | null) => void;
  /** Every field the form can have, in its usual order (built-in, then custom). */
  fields: readonly string[];
  /** Those a requester may see (the portal's form). */
  requesterFields: readonly string[];
  fieldLabel: (name: string) => string;
}) {
  const t = useLabel();
  const [audience, setAudience] = useState<LayoutAudience>('technician');
  const [previewing, setPreviewing] = useState(false);
  const own = audience === 'requester' ? (value?.requester ?? null) : (value?.technician ?? null);
  const part = own ?? value?.technician ?? null;
  const editable = value !== null && (audience === 'technician' || value.requester != null);

  const setPart = (next: LayoutPart) => {
    if (value === null) return;
    onChange(
      audience === 'technician' ? { ...value, technician: next } : { ...value, requester: next },
    );
  };
  const setSections = (sections: LayoutSection[]) => {
    if (part !== null) setPart({ ...part, sections });
  };
  const setSection = (index: number, section: LayoutSection) => {
    if (part === null) return;
    setSections(part.sections.map((s, i) => (i === index ? section : s)));
  };
  const placed = new Set(part?.sections.flatMap((s) => s.fields ?? []) ?? []);
  const unplaced = fields.filter((f) => !placed.has(f));
  const sectionLabel = (s: LayoutSection, index: number) =>
    s.names?.en ??
    Object.values(s.names ?? {})[0] ??
    t('templates.section_number', { n: index + 1 });

  return (
    <Space direction="vertical" style={{ width: '100%' }} data-testid="tpl-layout">
      <Typography.Title level={3} style={{ marginTop: 24 }}>
        {t('templates.layout')}
      </Typography.Title>
      <Typography.Paragraph type="secondary">{t('templates.layout_help')}</Typography.Paragraph>
      <Flex gap={16} wrap align="center">
        <Space>
          <Switch
            id="tpl-layout-on"
            checked={value !== null}
            onChange={(on) => {
              onChange(on ? { technician: blankPart(fields), requester: null } : null);
            }}
            data-testid="tpl-layout-on"
          />
          <label htmlFor="tpl-layout-on">{t('templates.layout_on')}</label>
        </Space>
        {value !== null && (
          <>
            <Segmented<LayoutAudience>
              aria-label={t('templates.layout_audience')}
              value={audience}
              onChange={setAudience}
              options={[
                { value: 'technician', label: t('templates.layout_audience_technician') },
                { value: 'requester', label: t('templates.layout_audience_requester') },
              ]}
              data-testid="tpl-layout-audience"
            />
            <Button
              icon={<EyeOutlined />}
              onClick={() => {
                setPreviewing(true);
              }}
              data-testid="tpl-layout-preview"
            >
              {t('templates.layout_preview')}
            </Button>
          </>
        )}
      </Flex>
      {value !== null && audience === 'requester' && (
        <Space>
          <Switch
            id="tpl-layout-requester-own"
            checked={value.requester != null}
            onChange={(on) => {
              onChange({ ...value, requester: on ? blankPart(requesterFields) : null });
            }}
            data-testid="tpl-layout-requester-own"
          />
          <label htmlFor="tpl-layout-requester-own">{t('templates.layout_requester_own')}</label>
        </Space>
      )}
      {value !== null && !editable && (
        <Typography.Text type="secondary" data-testid="tpl-layout-same">
          {t('templates.layout_requester_same')}
        </Typography.Text>
      )}
      {editable && part !== null && (
        <>
          <Form.Item label={t('templates.layout_label_position')} style={{ marginBottom: 8 }}>
            <Radio.Group
              value={part.label_position ?? 'top'}
              onChange={(event) => {
                setPart({ ...part, label_position: event.target.value as LabelPosition });
              }}
              options={(['top', 'start'] as const).map((p) => ({
                value: p,
                label: t(`form_label_position.${p}`),
              }))}
              data-testid="tpl-layout-labels"
            />
          </Form.Item>
          {part.sections.map((section, index) => {
            const title = sectionLabel(section, index);
            const own = section.fields ?? [];
            return (
              <Card
                key={section.id}
                size="small"
                title={<bdi dir="auto">{title}</bdi>}
                data-testid={`tpl-section-${String(index)}`}
                extra={
                  <Space size={4}>
                    <Button
                      size="small"
                      icon={<ArrowUpOutlined />}
                      disabled={index === 0}
                      aria-label={t('templates.section_up', { name: title })}
                      onClick={() => {
                        setSections(move(part.sections, index, index - 1));
                      }}
                    />
                    <Button
                      size="small"
                      icon={<ArrowDownOutlined />}
                      disabled={index === part.sections.length - 1}
                      aria-label={t('templates.section_down', { name: title })}
                      onClick={() => {
                        setSections(move(part.sections, index, index + 1));
                      }}
                    />
                    <Button
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      disabled={part.sections.length === 1}
                      aria-label={t('templates.section_remove', { name: title })}
                      onClick={() => {
                        setSections(part.sections.filter((_, i) => i !== index));
                      }}
                      data-testid={`tpl-section-${String(index)}-remove`}
                    />
                  </Space>
                }
              >
                <LabelsFields
                  value={section.names ?? {}}
                  onChange={(names) => {
                    setSection(index, { ...section, names });
                  }}
                  testId={`tpl-section-${String(index)}-name`}
                />
                <Flex gap={16} wrap style={{ marginBottom: 8 }}>
                  <Radio.Group
                    aria-label={t('templates.section_columns')}
                    value={section.columns ?? 1}
                    onChange={(event) => {
                      setSection(index, { ...section, columns: event.target.value as number });
                    }}
                    optionType="button"
                    options={[
                      { value: 1, label: t('templates.section_columns_one') },
                      { value: 2, label: t('templates.section_columns_two') },
                    ]}
                    data-testid={`tpl-section-${String(index)}-columns`}
                  />
                  <Space>
                    <Switch
                      size="small"
                      checked={section.collapsible === true}
                      aria-label={t('templates.section_collapsible')}
                      onChange={(on) => {
                        setSection(index, {
                          ...section,
                          collapsible: on,
                          collapsed: on && section.collapsed === true,
                        });
                      }}
                    />
                    {t('templates.section_collapsible')}
                  </Space>
                  <Space>
                    <Switch
                      size="small"
                      checked={section.collapsed === true}
                      disabled={section.collapsible !== true}
                      aria-label={t('templates.section_collapsed')}
                      onChange={(on) => {
                        setSection(index, { ...section, collapsed: on });
                      }}
                    />
                    {t('templates.section_collapsed')}
                  </Space>
                </Flex>
                {own.length === 0 && (
                  <Typography.Paragraph type="secondary">
                    {t('templates.section_empty')}
                  </Typography.Paragraph>
                )}
                <ol style={{ paddingInlineStart: 20, margin: 0 }}>
                  {own.map((name, at) => (
                    <li key={name} data-testid={`tpl-section-${String(index)}-field-${name}`}>
                      <Flex gap={8} align="center" wrap>
                        <bdi dir="auto" style={{ flex: '1 1 160px' }}>
                          {fieldLabel(name)}
                        </bdi>
                        <Button
                          size="small"
                          icon={<ArrowUpOutlined />}
                          disabled={at === 0}
                          aria-label={t('templates.field_up', { field: fieldLabel(name) })}
                          onClick={() => {
                            setSection(index, { ...section, fields: move(own, at, at - 1) });
                          }}
                        />
                        <Button
                          size="small"
                          icon={<ArrowDownOutlined />}
                          disabled={at === own.length - 1}
                          aria-label={t('templates.field_down', { field: fieldLabel(name) })}
                          onClick={() => {
                            setSection(index, { ...section, fields: move(own, at, at + 1) });
                          }}
                        />
                        {part.sections.length > 1 && (
                          <Select
                            size="small"
                            style={{ minWidth: 160 }}
                            aria-label={t('templates.field_move_to', { field: fieldLabel(name) })}
                            placeholder={t('templates.field_move_to_short')}
                            value={null}
                            onChange={(target: number) => {
                              setSections(
                                part.sections.map((s, i) => {
                                  if (i === index) {
                                    return {
                                      ...s,
                                      fields: (s.fields ?? []).filter((f) => f !== name),
                                    };
                                  }
                                  if (i === target)
                                    return { ...s, fields: [...(s.fields ?? []), name] };
                                  return s;
                                }),
                              );
                            }}
                            options={part.sections
                              .map((s, i) => ({ value: i, label: sectionLabel(s, i) }))
                              .filter((o) => o.value !== index)}
                            data-testid={`tpl-move-${name}`}
                          />
                        )}
                        <Button
                          size="small"
                          icon={<DeleteOutlined />}
                          aria-label={t('templates.field_remove', { field: fieldLabel(name) })}
                          onClick={() => {
                            setSection(index, {
                              ...section,
                              fields: own.filter((f) => f !== name),
                            });
                          }}
                        />
                      </Flex>
                    </li>
                  ))}
                </ol>
                {unplaced.length > 0 && (
                  <Select
                    size="small"
                    style={{ minWidth: 220, marginTop: 8 }}
                    aria-label={t('templates.field_add', { name: title })}
                    placeholder={t('templates.field_add_short')}
                    value={null}
                    showSearch
                    optionFilterProp="label"
                    onChange={(name: string) => {
                      setSection(index, { ...section, fields: [...own, name] });
                    }}
                    options={unplaced.map((f) => ({ value: f, label: fieldLabel(f) }))}
                    data-testid={`tpl-section-${String(index)}-add`}
                  />
                )}
              </Card>
            );
          })}
          {unplaced.length > 0 && (
            <Typography.Text type="secondary" data-testid="tpl-layout-unplaced">
              {t('templates.layout_unplaced')}
            </Typography.Text>
          )}
          <Button
            icon={<PlusOutlined />}
            disabled={part.sections.length >= 20}
            onClick={() => {
              setSections([...part.sections, { id: newId(), names: {}, fields: [] }]);
            }}
            data-testid="tpl-section-add"
          >
            {t('templates.section_add')}
          </Button>
        </>
      )}
      <LayoutPreview
        open={previewing}
        layout={value}
        fields={fields}
        requesterFields={requesterFields}
        fieldLabel={fieldLabel}
        onClose={() => {
          setPreviewing(false);
        }}
      />
    </Space>
  );
}

/** The form as each audience will see it, in either reading direction (REQ-INC-036 AC3). */
function LayoutPreview({
  open,
  layout,
  fields,
  requesterFields,
  fieldLabel,
  onClose,
}: {
  open: boolean;
  layout: FormLayout | null;
  fields: readonly string[];
  requesterFields: readonly string[];
  fieldLabel: (name: string) => string;
  onClose: () => void;
}) {
  const t = useLabel();
  const [audience, setAudience] = useState<LayoutAudience>('technician');
  const [direction, setDirection] = useState<'ltr' | 'rtl'>('ltr');
  const arranged = arrangeFields(
    layout,
    audience,
    audience === 'technician' ? fields : requesterFields,
  );
  const beside = arranged.labelPosition === 'start';
  return (
    <Modal
      open={open}
      title={t('templates.layout_preview')}
      onCancel={onClose}
      footer={null}
      width={760}
      data-testid="tpl-preview"
    >
      <Flex gap={16} wrap style={{ marginBottom: 16 }}>
        <Segmented<LayoutAudience>
          aria-label={t('templates.layout_audience')}
          value={audience}
          onChange={setAudience}
          options={[
            { value: 'technician', label: t('templates.layout_audience_technician') },
            { value: 'requester', label: t('templates.layout_audience_requester') },
          ]}
          data-testid="tpl-preview-audience"
        />
        <Segmented<'ltr' | 'rtl'>
          aria-label={t('templates.preview_direction')}
          value={direction}
          onChange={setDirection}
          options={[
            { value: 'ltr', label: t('templates.preview_ltr') },
            { value: 'rtl', label: t('templates.preview_rtl') },
          ]}
          data-testid="tpl-preview-direction"
        />
      </Flex>
      <ConfigProvider direction={direction} componentDisabled>
        <div dir={direction} data-testid="tpl-preview-form" data-direction={direction}>
          {arranged.sections.map((section, index) => (
            <Card
              key={section.id}
              size="small"
              title={section.names.en ?? t('templates.section_number', { n: index + 1 })}
              style={{ marginBottom: 12 }}
              data-testid={`tpl-preview-section-${section.id}`}
            >
              <Form
                component={false}
                layout={beside ? 'horizontal' : 'vertical'}
                labelCol={beside ? { flex: '150px' } : undefined}
              >
                <Flex wrap gap={12}>
                  {section.fields.map((name) => (
                    <Form.Item
                      key={name}
                      label={fieldLabel(name)}
                      style={{ flex: section.columns === 2 ? '1 1 45%' : '1 1 100%', margin: 0 }}
                    >
                      <Input aria-label={fieldLabel(name)} />
                    </Form.Item>
                  ))}
                </Flex>
              </Form>
            </Card>
          ))}
        </div>
      </ConfigProvider>
    </Modal>
  );
}
