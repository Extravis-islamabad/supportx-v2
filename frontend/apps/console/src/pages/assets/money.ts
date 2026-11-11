import { useAppearance } from '@supportx/ui';

/** Amounts in the tenant's base currency, exactly as the API sends them (strings, no floats). */
export function useMoney(currency: string | null | undefined) {
  const { intlLocale } = useAppearance();
  return (amount: string | null | undefined) => {
    if (amount === null || amount === undefined) return null;
    const options: Intl.NumberFormatOptions =
      currency === null || currency === undefined
        ? { minimumFractionDigits: 2 }
        : { style: 'currency', currency };
    // Display only: NUMERIC(14, 2) fits a double exactly to the cent; sums are the server's.
    return new Intl.NumberFormat(intlLocale, options).format(Number(amount));
  };
}

/** The empty value of a money figure in the asset pages: a dash, as the purchase card shows. */
export const NO_AMOUNT = '—';

/**
 * The total cost of ownership as shown (lane C's review on #375): a dash, never a blank or a
 * "0.00", while nothing is known: no total, or no purchase cost and no other cost recorded.
 */
export function totalShown(
  money: (amount: string | null | undefined) => string | null,
  figures: { total_cost: string | null; purchase: string | null },
): string {
  const nothing =
    figures.total_cost === null || (figures.purchase === null && Number(figures.total_cost) === 0);
  return nothing ? NO_AMOUNT : (money(figures.total_cost) ?? NO_AMOUNT);
}
