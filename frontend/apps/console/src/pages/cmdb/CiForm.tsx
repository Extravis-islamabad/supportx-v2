import { DatePicker, Flex, Form, Input, InputNumber, Select, Switch, TreeSelect } from 'antd';
import dayjs from 'dayjs';
import { useMemo } from 'react';

import { useCiStates, useCiTypes, useUnits, type CiInheritedAttribute } from '@supportx/api-client';
import { Controller, FormField, type UseFormReturn } from '@supportx/forms';
import {
  FIELD_WIDTH,
  FieldRow,
  FormSection,
  SPACE,
  lengthLimit,
  useAccess,
  useAppearance,
  useLabel,
} from '@supportx/ui';

import { DESCRIPTION_MAX, IMPACTS, NAME_MAX, type Values } from './form';
import { nameOf, typeTree } from './names';

/** One attribute's input, by its kind (the server checks the value too). */
function AttributeInput({
  attribute,
  value,
  onChange,
  id,
}: {
  attribute: CiInheritedAttribute;
  value: unknown;
  onChange: (value: unknown) => void;
  id: string;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  switch (attribute.type) {
    case 'number':
      return (
        <InputNumber
          id={id}
          value={typeof value === 'number' ? value : null}
          onChange={(next) => {
            onChange(next);
          }}
          style={{ width: FIELD_WIDTH.short }}
        />
      );
    case 'boolean':
      return (
        <Switch
          id={id}
          checked={value === true}
          onChange={(next) => {
            onChange(next);
          }}
        />
      );
    case 'date':
      return (
        <DatePicker
          id={id}
          value={typeof value === 'string' ? dayjs(value) : null}
          format="YYYY-MM-DD"
          onChange={(_, text) => {
            onChange(typeof text === 'string' && text !== '' ? text : null);
          }}
        />
      );
    case 'choice':
      return (
        <Select
          id={id}
          allowClear
          value={typeof value === 'string' ? value : undefined}
          onChange={(next: string | undefined) => {
            onChange(next ?? null);
          }}
          // Choices are codes an admin typed; shown as they are, no label exists for them.
          options={(attribute.choices ?? []).map((c) => ({ value: c, label: c }))}
          style={{ width: FIELD_WIDTH.medium }}
          aria-label={attribute.names[locale] ?? attribute.names.en ?? t('cmdb.field.attributes')}
        />
      );
    case 'long_text':
      return (
        <Input.TextArea
          id={id}
          rows={3}
          value={typeof value === 'string' ? value : ''}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      );
    default:
      return (
        <Input
          id={id}
          value={typeof value === 'string' ? value : ''}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      );
  }
}

/** The CI's fields (template B sections, D-147): what it is, who has it, and its attributes. */
export function CiFields({
  form,
  typeLocked = false,
}: {
  form: UseFormReturn<Values>;
  typeLocked?: boolean;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { can } = useAccess();
  const types = useCiTypes();
  const states = useCiStates();
  const sites = useUnits('sites', can('sites.view'));
  const groups = useUnits('groups', can('groups.view'));
  const typeId = form.watch('type_id');
  const tree = useMemo(
    () => typeTree(types.data?.items ?? [], (x) => nameOf(t, locale, x, 'cmdb_ci_type')),
    [types.data, t, locale],
  );
  const attributes = types.data?.items.find((x) => x.id === typeId)?.inherited_attributes ?? [];
  const impactOptions = IMPACTS.map((value) => ({ value, label: t(`cmdb_impact.${value}`) }));
  const unitOptions = (units: typeof sites) =>
    (units.data ?? []).map((u) => ({ value: u.id, label: u.name }));
  return (
    <Form layout="vertical" component="div">
      <Flex vertical gap={SPACE.md}>
        <FormSection title={t('cmdb.title.new_ci')} testId="ci-section-main">
          <FormField
            control={form.control}
            name="name"
            labelKey="cmdb.field.name"
            required
            render={(field) => (
              <Input {...field} count={lengthLimit(NAME_MAX)} data-testid="ci-name" />
            )}
          />
          <FieldRow>
            <FormField
              control={form.control}
              name="type_id"
              labelKey="cmdb.field.type_id"
              required
              render={({ value, onChange, id }) => (
                <TreeSelect
                  id={id}
                  disabled={typeLocked}
                  treeDefaultExpandAll
                  value={value === '' ? undefined : value}
                  onChange={(next: string) => {
                    onChange(next);
                  }}
                  treeData={tree}
                  data-testid="ci-type"
                />
              )}
            />
            <FormField
              control={form.control}
              name="state_id"
              labelKey="cmdb.field.state_id"
              render={({ value, onChange, id }) => (
                <Select
                  id={id}
                  value={value ?? undefined}
                  onChange={(next: string) => {
                    onChange(next);
                  }}
                  options={(states.data?.items ?? []).map((s) => ({
                    value: s.id,
                    label: nameOf(t, locale, s, 'cmdb_ci_state'),
                  }))}
                  data-testid="ci-state"
                />
              )}
            />
          </FieldRow>
          <FormField
            control={form.control}
            name="description"
            labelKey="cmdb.field.description"
            render={(field) => (
              <Input.TextArea {...field} rows={4} count={lengthLimit(DESCRIPTION_MAX)} />
            )}
          />
          <FieldRow>
            {(['business_impact', 'criticality'] as const).map((name) => (
              <FormField
                key={name}
                control={form.control}
                name={name}
                labelKey={`cmdb.field.${name}`}
                render={({ value, onChange, id }) => (
                  <Select
                    id={id}
                    allowClear
                    value={value ?? undefined}
                    onChange={(next: (typeof IMPACTS)[number] | undefined) => {
                      onChange(next ?? null);
                    }}
                    options={impactOptions}
                  />
                )}
              />
            ))}
          </FieldRow>
        </FormSection>
        <FormSection title={t('cmdb.field.owner_group_id')} testId="ci-section-owners">
          <FieldRow>
            {(['site_id', 'owner_group_id', 'managed_by_group_id'] as const).map((name) => (
              <FormField
                key={name}
                control={form.control}
                name={name}
                labelKey={`cmdb.field.${name}`}
                render={({ value, onChange, id }) => (
                  <Select
                    id={id}
                    allowClear
                    showSearch
                    optionFilterProp="label"
                    value={value ?? undefined}
                    onChange={(next: string | undefined) => {
                      onChange(next ?? null);
                    }}
                    options={unitOptions(name === 'site_id' ? sites : groups)}
                  />
                )}
              />
            ))}
          </FieldRow>
        </FormSection>
        {attributes.length > 0 && (
          <FormSection title={t('cmdb.field.attributes')} testId="ci-section-attributes">
            <FieldRow>
              {attributes.map((attribute) => (
                <Controller
                  key={attribute.key}
                  control={form.control}
                  name={`custom.${attribute.key}`}
                  render={({ field }) => (
                    <Form.Item
                      label={attribute.names[locale] ?? attribute.names.en}
                      htmlFor={`attr-${attribute.key}`}
                      required={attribute.required}
                    >
                      <AttributeInput
                        attribute={attribute}
                        value={field.value}
                        onChange={field.onChange}
                        id={`attr-${attribute.key}`}
                      />
                    </Form.Item>
                  )}
                />
              ))}
            </FieldRow>
          </FormSection>
        )}
      </Flex>
    </Form>
  );
}
