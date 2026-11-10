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
