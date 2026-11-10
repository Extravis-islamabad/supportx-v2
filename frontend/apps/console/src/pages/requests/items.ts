import type { useLabel } from '@supportx/ui';
import type { CatalogItem } from '@supportx/api-client';

/** An item's name in the viewer's language, English as the fallback. */
export function itemName(item: Pick<CatalogItem, 'names'> | undefined, locale: string): string {
  if (item === undefined) return '';
  return item.names[locale] ?? item.names.en ?? '';
}

type Translate = ReturnType<typeof useLabel>;

/** "Usually delivered within N working days" from the SLA that would apply (Haider, 2026-11-10). */
export function deliveryText(
  t: Translate,
  delivery: { amount: number; unit: string; around_the_clock: boolean } | null | undefined,
): string | null {
  if (delivery == null) return null;
  const { amount, unit, around_the_clock: aroundTheClock } = delivery;
  if (unit === 'business_days') return t('requests.delivery.working_days', { count: amount });
  // Minutes of an hour or more say hours, rounded up: "about a day" never reads as minutes.
  const hours = unit === 'hours' ? amount : amount >= 60 ? Math.ceil(amount / 60) : null;
  if (hours === null) return t('requests.delivery.minutes', { count: amount });
  return t(aroundTheClock ? 'requests.delivery.hours' : 'requests.delivery.working_hours', {
    count: hours,
  });
}
