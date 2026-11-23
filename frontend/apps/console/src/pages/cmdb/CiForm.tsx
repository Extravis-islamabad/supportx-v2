import { Flex, Form, Input, Select, TreeSelect } from 'antd';
import { useEffect, useMemo } from 'react';

import { useCiStates, useCiTypes, useCustomFields, useUnits } from '@supportx/api-client';
import { FormField, type UseFormReturn } from '@supportx/forms';
import {
  FieldRow,
  FormSection,
  SPACE,
  lengthLimit,
  useAccess,
  useAppearance,
  useLabel,
} from '@supportx/ui';

import { CustomFormField } from '../customFields/fields';
import { DESCRIPTION_MAX, IMPACTS, NAME_MAX, type Values } from './form';
import { nameOf, typeTree } from './names';

/**
 * The CI's fields (template B sections, D-147): what it is and who has it, then the custom fields
 * of its type (0175: the type's own and those of the types above it). A field the person's roles
 * may only read (`readOnly`, ADR-047) is not offered here; the record shows it.
 */
export function CiFields({
  form,
  typeLocked = false,
  readOnly = [],
}: {
  form: UseFormReturn<Values>;
  typeLocked?: boolean;
  readOnly?: readonly string[];
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { can } = useAccess();
  const types = useCiTypes();
  const states = useCiStates();
  const sites = useUnits('sites', can('sites.view'));
  const groups = useUnits('groups', can('groups.view'));
  const tree = useMemo(
    () => typeTree(types.data?.items ?? [], (x) => nameOf(t, locale, x, 'cmdb_ci_type')),
    [types.data, t, locale],
  );
  const typeId = form.watch('type_id');
  const custom = useCustomFields('ci', false, typeId !== '', { typeId });
  const offered = (custom.data ?? []).filter(
    (f) => !f.retired && !readOnly.includes(`custom.${f.key}`),
  );
  // A type chosen anew keeps only the values its fields take (the server refuses the others).
  useEffect(() => {
    if (custom.data === undefined) return;
    const keys = new Set(custom.data.map((f) => f.key));
    const held = form.getValues('custom');
    const kept = Object.fromEntries(Object.entries(held).filter(([k]) => keys.has(k)));
    if (Object.keys(kept).length !== Object.keys(held).length) form.setValue('custom', kept);
  }, [custom.data, form]);
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
        {offered.length > 0 && (
          <FormSection title={t('cmdb.section.custom_fields')} testId="ci-section-custom">
            {offered.map((field) => (
              <CustomFormField
                key={field.id}
                control={form.control}
                field={field}
                required={field.validation.required}
              />
            ))}
          </FormSection>
        )}
      </Flex>
    </Form>
  );
}
