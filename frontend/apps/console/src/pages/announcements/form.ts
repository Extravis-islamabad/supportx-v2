import type {
  Announcement,
  AnnouncementAudience,
  AnnouncementSeverity,
} from '@supportx/api-client';
import { z } from '@supportx/forms';

/** The announcement form's rules and conversions (WP-012); the fields are in AnnouncementForm. */
export const SEVERITIES: AnnouncementSeverity[] = ['info', 'warning', 'critical'];
export const AUDIENCES: AnnouncementAudience[] = ['everyone', 'sites', 'groups'];
export const TITLE_MAX = 200;
export const BODY_MAX = 20_000;

export const schema = z
  .object({
    title: z
      .string()
      .trim()
      .min(1, 'errors.field.required')
      .max(TITLE_MAX, 'errors.field.value_too_long'),
    body: z
      .string()
      .trim()
      .min(1, 'errors.field.required')
      .max(BODY_MAX, 'errors.field.value_too_long'),
    severity: z.enum(['info', 'warning', 'critical']),
    audience: z.enum(['everyone', 'sites', 'groups']),
    site_ids: z.array(z.string()),
    group_ids: z.array(z.string()),
    show_as_banner: z.boolean(),
    publish_from: z.string().nullable(),
    publish_until: z.string().nullable(),
  })
  .refine(
    (v) => v.publish_from === null || v.publish_until === null || v.publish_until > v.publish_from,
    { path: ['publish_until'], message: 'errors.field.window_end_before_start' },
  );
export type Values = z.infer<typeof schema>;
export const FIELDS = [
  'title',
  'body',
  'severity',
  'audience',
  'site_ids',
  'group_ids',
  'show_as_banner',
  'publish_from',
  'publish_until',
] as const;
export type Field = (typeof FIELDS)[number];

export const EMPTY: Values = {
  title: '',
  body: '',
  severity: 'info',
  audience: 'everyone',
  site_ids: [],
  group_ids: [],
  show_as_banner: true,
  publish_from: null,
  publish_until: null,
};

export function valuesOf(item: Announcement): Values {
  return {
    title: item.title,
    body: item.body,
    severity: item.severity,
    audience: item.audience,
    site_ids: item.site_ids,
    group_ids: item.group_ids,
    show_as_banner: item.show_as_banner,
    publish_from: item.publish_from,
    publish_until: item.publish_until,
  };
}

/** What to send: only the units of the chosen audience (the API refuses the others). */
export function bodyOf(values: Values, fields: readonly Field[] = FIELDS) {
  const clean = {
    ...values,
    site_ids: values.audience === 'sites' ? values.site_ids : [],
    group_ids: values.audience === 'groups' ? values.group_ids : [],
  };
  const sent = new Set<Field>(fields);
  if (sent.has('audience')) {
    sent.add('site_ids');
    sent.add('group_ids');
  }
  return Object.fromEntries([...sent].map((name) => [name, clean[name]])) as Partial<Values>;
}
