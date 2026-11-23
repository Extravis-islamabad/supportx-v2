/**
 * Quantities are exact decimals sent as strings ("20.000"); shown as people write them ("20",
 * "2.5"), never through a float, so 0.1 + 0.2 never shows as 0.30000000000000004.
 */
export function plainQuantity(value: string | number): string {
  const text = String(value).trim();
  if (!text.includes('.')) return text;
  const trimmed = text.replace(/0+$/, '').replace(/\.$/, '');
  return trimmed === '-0' || trimmed === '' ? '0' : trimmed;
}

/** "-2.000" → "2": an allocation's size without its sign (the ledger shows the kind). */
export function unsignedQuantity(value: string): string {
  return plainQuantity(value.replace(/^-/, ''));
}

/**
 * A stock's level against its minimum, as the label key to show (QA 2026-11-11 F-15): the server
 * flags `low` at or below the minimum; below it says so, never "At minimum". Null when not low.
 */
export function stockLevelKey(stock: {
  low: boolean;
  quantity: string;
  minimum: string | null;
}): 'assets.stock.below_minimum' | 'assets.stock.low' | null {
  if (!stock.low) return null;
  // Exact decimals of three places at most: a double compares them correctly.
  return stock.minimum !== null && Number(stock.quantity) < Number(stock.minimum)
    ? 'assets.stock.below_minimum'
    : 'assets.stock.low';
}
