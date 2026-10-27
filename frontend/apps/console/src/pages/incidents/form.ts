import type { IncidentCatalogue, IncidentInput } from '@supportx/api-client';
import { z } from '@supportx/forms';

/** The create form's rules and conversions (WP-020); the fields are in NewIncidentPage. */
/** The API's limit (WorkItemIn.subject); the form shows a counter (QA BUG-10). */
export const SUBJECT_MAX = 500;
/** The API's limit for impact details (plain text). */
export const IMPACT_DETAILS_MAX = 2000;

export const schema = z
  .object({
    subject: z
      .string()
      .trim()
      .min(1, 'errors.field.required')
      .max(SUBJECT_MAX, 'errors.field.value_too_long'),
    description: z.string(),
    requester_id: z
      .string()
      .nullable()
      .refine((v): boolean => v !== null, 'errors.field.required'),
    on_behalf_of_id: z.string().nullable(),
    channel: z.enum(['phone', 'walk_up']),
    site_id: z.string().nullable(),
    department_id: z.string().nullable(),
    group_id: z.string().nullable(),
    technician_id: z.string().nullable(),
    category_id: z.string().nullable(),
    impact: z.string().nullable(),
    impact_details: z.string().max(IMPACT_DETAILS_MAX, 'errors.field.value_too_long'),
    urgency: z.string().nullable(),
    level: z.string().nullable(),
    priority: z.string().nullable(), // null: from the matrix
    priority_reason: z.string().max(500, 'errors.field.value_too_long'),
    tags: z.array(z.string()),
    // Custom field values by key (WP-026); checked by the server, required ones by the page.
    custom: z.record(z.string(), z.unknown()),
  })
  .refine((v) => v.priority === null || v.priority_reason.trim() !== '', {
    path: ['priority_reason'],
    message: 'errors.field.required',
  });
export type Values = z.infer<typeof schema>;
export const FIELDS = [
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
  'impact',
  'impact_details',
  'urgency',
  'level',
  'priority',
  'priority_reason',
  'tags',
] as const;

export const EMPTY: Values = {
  subject: '',
  description: '',
  requester_id: null,
  on_behalf_of_id: null,
  channel: 'phone',
  site_id: null,
  department_id: null,
  group_id: null,
  technician_id: null,
  category_id: null,
  impact: null,
  impact_details: '',
  urgency: null,
  level: null,
  priority: null,
  priority_reason: '',
  tags: [],
  custom: {},
};

/** The priority the server will compute (REQ-INC-009 AC2), shown live while typing. */
export function previewPriority(
  catalogue: IncidentCatalogue | undefined,
  impact: string | null,
  urgency: string | null,
): { priority: string; source: 'matrix' } | null {
  // Only a real matrix value: with impact or urgency blank the form says the priority is
  // "calculated when impact and urgency are set" instead of showing a default (form review).
  if (catalogue === undefined || impact === null || urgency === null) return null;
  const cell = catalogue.matrix.find((c) => c.impact === impact && c.urgency === urgency);
  return cell === undefined ? null : { priority: cell.priority, source: 'matrix' };
}

/** What to send: empty optional values are left out; a matrix priority sends no override. */
export function bodyOf(
  values: Values,
  confirmLoseAccess = false,
  templateId: string | null = null,
  customKeys: readonly string[] = [],
): IncidentInput {
  const body: Record<string, unknown> = {
    subject: values.subject.trim(),
    requester_id: values.requester_id,
    channel: values.channel,
    tags: values.tags,
    confirm_lose_access: confirmLoseAccess,
  };
  if (templateId !== null) body.template_id = templateId;
  if (values.description !== '') body.description = values.description;
  if (values.impact_details.trim() !== '') body.impact_details = values.impact_details.trim();
  for (const name of [
    'on_behalf_of_id',
    'site_id',
    'department_id',
    'group_id',
    'technician_id',
    'category_id',
    'impact',
    'urgency',
    'level',
  ] as const) {
    if (values[name] !== null) body[name] = values[name];
  }
  if (values.priority !== null) {
    body.priority = values.priority;
    body.priority_reason = values.priority_reason.trim();
  }
  // Every custom field on screen, empty ones as null: an emptied default stays empty.
  if (customKeys.length > 0) {
    body.custom = Object.fromEntries(
      customKeys.map((key) => {
        const value = values.custom[key];
        return [key, hasValue(value) ? value : null];
      }),
    );
  }
  return body as unknown as IncidentInput;
}

/** Whether a form value counts as filled in (an empty editor paragraph does not). */
export function hasValue(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === 'string') {
    return (
      value
        .replace(/<[^>]*>/g, '')
        .replace(/&nbsp;/g, ' ')
        .trim() !== ''
    );
  }
  return true;
}
