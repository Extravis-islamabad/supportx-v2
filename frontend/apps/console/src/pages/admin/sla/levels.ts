import type { useLabel } from '@supportx/ui';

type T = ReturnType<typeof useLabel>;

/** A level's place on the clock, for people: "1 business hour before the due time". */
export function levelWhen(
  t: T,
  level: { anchor: 'due' | 'warning'; offset_seconds: number },
): string {
  const anchor = t(`sla.level.anchor_in_sentence.${level.anchor}`);
  const seconds = Math.abs(level.offset_seconds);
  if (seconds === 0) return t('sla.level.when_at', { anchor });
  const amount =
    seconds % 3600 === 0
      ? t('sla.level.hours', { count: seconds / 3600 })
      : t('sla.level.minutes', { count: Math.round(seconds / 60) });
  return t(level.offset_seconds < 0 ? 'sla.level.when_before' : 'sla.level.when_after', {
    amount,
    anchor,
  });
}
