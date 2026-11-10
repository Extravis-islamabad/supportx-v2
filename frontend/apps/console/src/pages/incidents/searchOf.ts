import type { FilterExpression } from '@supportx/api-client';
import { stripIsolates } from '@supportx/labels';

const ID_PATTERN = /^([A-Za-z]{2,6}-)?\d{1,18}$/;

/** Subject words, or a display ID ("INC-12", "12"), in one search box. */
export function searchOf(typed: string): FilterExpression | undefined {
  // A pasted ID or subject may carry directional marks from a screen (isolation rule).
  const text = stripIsolates(typed).trim();
  if (text === '') return undefined;
  const subject: FilterExpression = { field: 'subject', op: 'contains', value: text };
  if (!ID_PATTERN.test(text)) return subject;
  const number = Number(text.replace(/^[A-Za-z]+-/, ''));
  return { or: [subject, { field: 'display_number', op: 'eq', value: number }] };
}
