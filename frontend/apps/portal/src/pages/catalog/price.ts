import type { CatalogItem } from '@supportx/api-client';
import type { useLabel } from '@supportx/ui';

type Translate = ReturnType<typeof useLabel>;

/**
 * An amount in the tenant's base currency, in the reader's number format (REQ-CAT-020 AC3).
 * Display only: amounts come from the server as decimal text; sums are the server's.
 */
export function moneyText(
  amount: string | number | null | undefined,
  currency: string | null | undefined,
  intlLocale: string,
): string | null {
  if (amount === null || amount === undefined || amount === '') return null;
  const options: Intl.NumberFormatOptions =
    currency == null ? { minimumFractionDigits: 2 } : { style: 'currency', currency };
  return new Intl.NumberFormat(intlLocale, options).format(Number(amount));
}

/** "40.00 per month" for a recurring price, the amount alone when once (REQ-CAT-020 AC2). */
export function periodText(t: Translate, amount: string, period: string | null | undefined) {
  return period != null && period !== 'once'
    ? t(`requests.price_per.${period}` as Parameters<Translate>[0], { amount })
    : amount;
}

/** The item's price as the portal shows it, or null when it has none (or none is shown). */
export function priceText(t: Translate, item: CatalogItem, intlLocale: string): string | null {
  const amount = moneyText(item.price, item.currency, intlLocale);
  return amount === null ? null : periodText(t, amount, item.price_period);
}

/**
 * The form's live estimate (D-184), the server's rule: (the price + the chosen options' prices)
 * times the quantity; null when nothing is priced. The request keeps the server's own snapshot.
 */
export function estimateOf(
  item: CatalogItem,
  answers: Record<string, unknown>,
  quantity: number | null,
): number | null {
  const base = item.price == null ? null : Number(item.price);
  let extras = 0;
  let priced = false;
  for (const q of item.questions) {
    const prices = q.option_prices ?? {};
    const answer = answers[q.key];
    const chosen = (Array.isArray(answer) ? answer : [answer]).filter(
      (code): code is string => typeof code === 'string',
    ); // a choice's answer is its code (text)
    for (const code of chosen) {
      const amount = prices[code];
      if (amount !== undefined) {
        extras += Number(amount);
        priced = true;
      }
    }
  }
  if (base === null && !priced) return null;
  return ((base ?? 0) + extras) * Math.max(quantity ?? 1, 1);
}
