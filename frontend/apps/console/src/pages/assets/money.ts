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
