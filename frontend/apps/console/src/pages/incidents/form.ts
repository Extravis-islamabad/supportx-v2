import type { IncidentCatalogue, IncidentInput } from '@supportx/api-client';
import { z } from '@supportx/forms';

/** The create form's rules and conversions (WP-020); the fields are in NewIncidentPage. */
/** The API's limit (WorkItemIn.subject); the form shows a counter (QA BUG-10). */
export const SUBJECT_MAX = 500;

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
    group_id: z.string().nullable(),
    technician_id: z.string().nullable(),
    category_id: z.string().nullable(),
    impact: z.string().nullable(),
    urgency: z.string().nullable(),
    priority: z.string().nullable(), // null: from the matrix
    priority_reason: z.string().max(500, 'errors.field.value_too_long'),
    tags: z.array(z.string()),
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
  'group_id',
  'technician_id',
  'category_id',
  'impact',
  'urgency',
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
  group_id: null,
  technician_id: null,
  category_id: null,
  impact: null,
  urgency: null,
  priority: null,
  priority_reason: '',
  tags: [],
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
export function bodyOf(values: Values, confirmLoseAccess = false): IncidentInput {
  const body: Record<string, unknown> = {
    subject: values.subject.trim(),
    requester_id: values.requester_id,
    channel: values.channel,
    tags: values.tags,
    confirm_lose_access: confirmLoseAccess,
  };
  if (values.description !== '') body.description = values.description;
  for (const name of [
    'on_behalf_of_id',
    'site_id',
    'group_id',
    'technician_id',
    'category_id',
    'impact',
    'urgency',
  ] as const) {
    if (values[name] !== null) body[name] = values[name];
  }
  if (values.priority !== null) {
    body.priority = values.priority;
    body.priority_reason = values.priority_reason.trim();
  }
  return body as unknown as IncidentInput;
}
