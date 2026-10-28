import { useCustomFields, type Incident } from '@supportx/api-client';
import { useAppearance, useLabel } from '@supportx/ui';

import { fieldName } from '../customFields/values';

// What a person sees and changes of an incident: compared by the conflict dialog when the
// server cannot name the fields (QA WP-029 BUG-05; incidents normally keep field history).
const VIEWED = [
  'subject',
  'description',
  'requester_id',
  'on_behalf_of_id',
  'channel',
  'site_id',
  'department_id',
  'group_id',
  'technician_id',
  'category_id',
  'level',
  'impact',
  'urgency',
  'impact_details',
  'priority',
  'tags',
  'status',
  'status_reason_code',
] as const;

/** An incident as its page shows it, custom fields as `custom.<key>`. */
export function incidentView(item: Incident | undefined): object | undefined {
  if (item === undefined) return undefined;
  return {
    ...Object.fromEntries(VIEWED.map((field) => [field, item[field]])),
    ...Object.fromEntries(Object.entries(item.custom).map(([key, v]) => [`custom.${key}`, v])),
  };
}

/** An incident field's name in words: built-in, or the admin's name of a custom field. */
export function useIncidentFieldName(): (field: string) => string {
  const t = useLabel();
  const { locale } = useAppearance();
  const customFields = useCustomFields('incident');
  return (field) => {
    if (!field.startsWith('custom.')) return t(`work_item.field.${field}`);
    const found = customFields.data?.find((f) => `custom.${f.key}` === field);
    return found === undefined ? t('custom_fields.unknown_field') : fieldName(found, locale);
  };
}
