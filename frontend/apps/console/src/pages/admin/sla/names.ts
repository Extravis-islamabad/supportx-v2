import type { useLabel } from '@supportx/ui';

type Translate = ReturnType<typeof useLabel>;

// The name the server gives every tenant's fallback policy (sla service FALLBACK_NAME).
const FALLBACK_ENGLISH = 'Default policy';

/**
 * A policy's name for people (QA V6, QA6-SLA-01): the seeded fallback policy in the user's
 * language while it keeps its seeded name; a name someone typed stays as typed.
 */
export function policyName(t: Translate, name: string | null | undefined): string {
  if (name === FALLBACK_ENGLISH) return t('sla_policy.fallback');
  return name ?? '';
}

// The names the server gives every tenant's two system calendars (sla service calendars.py).
const SYSTEM_CALENDARS: Record<string, string> = {
  'Around the clock': 'sla_calendar.around_the_clock',
  'Operating hours': 'sla_calendar.operating_hours',
};

/** A calendar's name for people (QA V6): the seeded system calendars in the user's language. */
export function calendarNameOf(t: Translate, name: string | null | undefined): string {
  const key = name == null ? undefined : SYSTEM_CALENDARS[name];
  return key === undefined ? (name ?? '') : t(key);
}
