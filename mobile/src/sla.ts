import { useEffect, useState } from 'react';

import type { Tone } from './tones';
import { TONES } from './tones';

type Translate = (key: string, params?: Record<string, string | number>) => string;

/** Now, ticking every `everyMs`: the SLA countdown moves on its own (REQ-SLA-038). */
export function useNow(everyMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now());
    }, everyMs);
    return () => {
      clearInterval(timer);
    };
  }, [everyMs]);
  return now;
}

/** A span of wall time in words, as on the web: "2 d 3 h", "4 h 10 min", "25 min". */
export function span(t: Translate, ms: number): string {
  const minutes = Math.max(Math.floor(ms / 60_000), 0);
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  if (days > 0) return t('incidents.sla.span_days', { days, hours });
  if (hours > 0) return t('incidents.sla.span_hours', { hours, minutes: minutes % 60 });
  return t('incidents.sla.span_minutes', { minutes });
}

export interface SlaView {
  text: string;
  tone: Tone;
  late: boolean;
}

/** The resolution SLA of a record at a glance: due in / overdue by, or its state. */
export function slaView(
  t: Translate,
  now: number,
  record: {
    sla_policy_id: string | null;
    resolution_due_at: string | null;
    resolution_sla_state?: string | null;
  },
): SlaView {
  if (record.sla_policy_id === null) {
    return { text: t('incidents.no_sla'), tone: TONES.neutral, late: false };
  }
  const state = record.resolution_sla_state;
  if (record.resolution_due_at === null) {
    return {
      text: state ? t(`sla_target_state.${state}`) : t('incidents.no_sla'),
      tone: state === 'met' ? TONES.success : TONES.neutral,
      late: false,
    };
  }
  const left = Date.parse(record.resolution_due_at) - now;
  const late = left < 0 || state === 'breached';
  if (late) {
    return {
      text: t('incidents.sla.overdue_by', { time: span(t, -left) }),
      tone: TONES.danger,
      late: true,
    };
  }
  return {
    text: t('incidents.sla.due_in', { time: span(t, left) }),
    tone: state === 'warning' ? TONES.warning : TONES.success,
    late: false,
  };
}
