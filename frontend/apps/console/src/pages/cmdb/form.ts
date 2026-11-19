import { ApiError, type Ci, type CiInput, type CiPatch } from '@supportx/api-client';
import { z, type Path } from '@supportx/forms';

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
  // Custom values by key (0175): the fields of the CI's type and the types above it.
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

const empty = (value: unknown) =>
  value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length);

/**
 * The form fields a refusal names: the built-in ones, and each `custom.<key>` it names (a
 * required custom field may have no value in the form yet).
 */
export function errorFields(error: unknown): readonly Path<Values>[] {
  if (!(error instanceof ApiError)) return FIELDS;
  const custom = error.fieldErrors
    .map((f) => f.field.replace(/^body\./, ''))
    .filter((name): name is `custom.${string}` => name.startsWith('custom.'));
  return [...FIELDS, ...custom];
}

/** The form's values as the API takes them (empty text left out). */
export function bodyOf(values: Values): CiInput {
  return {
    ...values,
    name: values.name.trim(),
    description: values.description.trim() === '' ? null : values.description,
    custom: Object.fromEntries(Object.entries(values.custom).filter(([, v]) => !empty(v))),
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

/**
 * An edit's fields (the type changes through its own action). Custom values go only when changed
 * (a cleared one as null), so a field the person may only read is never sent.
 */
export function patchOf(values: Values, saved: Ci['custom'] = {}): CiPatch {
  const body = bodyOf(values);
  const custom: Record<string, unknown> = {};
  for (const key of new Set([...Object.keys(values.custom), ...Object.keys(saved)])) {
    const next = empty(values.custom[key]) ? null : values.custom[key];
    const before = empty(saved[key]) ? null : saved[key];
    if (JSON.stringify(next) !== JSON.stringify(before)) custom[key] = next;
  }
  return {
    ...(Object.keys(custom).length > 0 ? { custom } : {}),
    name: body.name,
    description: body.description,
    state_id: body.state_id,
    site_id: body.site_id,
    owner_group_id: body.owner_group_id,
    managed_by_group_id: body.managed_by_group_id,
    business_impact: body.business_impact,
    criticality: body.criticality,
  };
}
