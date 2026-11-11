import type { useLabel } from '@supportx/ui';

// SLA times in words (shared by the SLA tag, the restore warning and the history).

type Translate = ReturnType<typeof useLabel>;

/** A span of wall time in words: "2 d 3 h", "4 h 10 min", "25 min". */
export function span(t: Translate, ms: number): string {
  const minutes = Math.max(Math.floor(ms / 60_000), 0);
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  if (days > 0) return t('incidents.sla.span_days', { days, hours });
  if (hours > 0) return t('incidents.sla.span_hours', { hours, minutes: minutes % 60 });
  return t('incidents.sla.span_minutes', { minutes });
}

/** One open target's standing as a history line or warning ("first response overdue by 3 h"). */
export function slaStanding(t: Translate, kind: string, state: string, seconds: number): string {
  const target = t(`sla_target_kind.${kind}`);
  const time = span(t, seconds * 1000);
  return t(`history.sla_on_restore.${state === 'left' || state === 'paused' ? state : 'overdue'}`, {
    target,
    time,
  });
}

const OPEN_SLA = new Set(['running', 'paused', 'breached']);

/**
 * Where a restored record's open targets stand (Haider, 2026-11-10: the clock keeps running in
 * the trash, so a restore warns), from the record as the restore returned it.
 */
export function restoredStanding(
  t: Translate,
  item: {
    first_response_due_at?: string | null;
    first_response_sla_state?: string | null;
    resolution_due_at?: string | null;
    resolution_sla_state?: string | null;
  },
  now: number,
): string[] {
  const found: string[] = [];
  const targets = [
    ['first_response', item.first_response_sla_state, item.first_response_due_at],
    ['resolution', item.resolution_sla_state, item.resolution_due_at],
  ] as const;
  for (const [kind, state, due] of targets) {
    if (state == null || !OPEN_SLA.has(state)) continue;
    if (state === 'paused' || due == null) {
      found.push(slaStanding(t, kind, 'paused', 0));
      continue;
    }
    const left = Math.round((Date.parse(due) - now) / 1000);
    found.push(slaStanding(t, kind, left > 0 ? 'left' : 'overdue', Math.abs(left)));
  }
  return found;
}
