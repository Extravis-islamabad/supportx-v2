import type { Ci, CiInput, CiPatch } from '@supportx/api-client';
import { z } from '@supportx/forms';

/** The CI form's rules and conversions (WP-053 S1); the fields are in CiForm. */
export const IMPACTS = ['low', 'medium', 'high', 'critical'] as const;
export const NAME_MAX = 200;
export const DESCRIPTION_MAX = 10_000;

const impact = z.enum(IMPACTS).nullable();
export const schema = z.object({
  type_id: z.string().min(1, 'errors.field.required'),
  name: z
    .string()
    .trim()
    .min(1, 'errors.field.required')
    .max(NAME_MAX, 'errors.field.value_too_long'),
  description: z.string().max(DESCRIPTION_MAX, 'errors.field.value_too_long'),
  state_id: z.string().nullable(),
  site_id: z.string().nullable(),
  owner_group_id: z.string().nullable(),
  managed_by_group_id: z.string().nullable(),
  business_impact: impact,
  criticality: impact,
  // Attribute values by key; the server checks them against the type's attributes.
  custom: z.record(z.string(), z.unknown()),
});
export type Values = z.infer<typeof schema>;
export const FIELDS = [
  'type_id',
  'name',
  'description',
  'state_id',
  'site_id',
  'owner_group_id',
  'managed_by_group_id',
  'business_impact',
  'criticality',
] as const;

export const EMPTY: Values = {
  type_id: '',
  name: '',
  description: '',
  state_id: null,
  site_id: null,
  owner_group_id: null,
  managed_by_group_id: null,
  business_impact: null,
  criticality: null,
  custom: {},
};

/** The form's values as the API takes them (empty text and empty values left out). */
export function bodyOf(values: Values): CiInput {
  const custom = Object.fromEntries(
    Object.entries(values.custom).filter(([, v]) => v !== undefined && v !== null && v !== ''),
  );
  return {
    ...values,
    name: values.name.trim(),
    description: values.description.trim() === '' ? null : values.description,
    custom,
  };
}

/** A saved CI as the form's values. */
export function valuesOf(ci: Ci): Values {
  return {
    type_id: ci.type_id,
    name: ci.name,
    description: ci.description ?? '',
    state_id: ci.state_id,
    site_id: ci.site_id,
    owner_group_id: ci.owner_group_id,
    managed_by_group_id: ci.managed_by_group_id,
    business_impact: ci.business_impact,
    criticality: ci.criticality,
    custom: { ...ci.custom },
  };
}

/** An edit's fields (the type changes through its own action, with a preview). */
export function patchOf(values: Values): CiPatch {
  const body = bodyOf(values);
  return {
    name: body.name,
    description: body.description,
    state_id: body.state_id,
    site_id: body.site_id,
    owner_group_id: body.owner_group_id,
    managed_by_group_id: body.managed_by_group_id,
    business_impact: body.business_impact,
    criticality: body.criticality,
    custom: body.custom,
  };
}
