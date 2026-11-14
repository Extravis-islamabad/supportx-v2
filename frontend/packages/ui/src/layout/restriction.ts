export type RestrictionKind = 'hidden' | 'masked';

/** The restriction of a field on a record that lists its hidden and masked fields, if any. */
export function restrictionOf(
  record: { hidden_fields?: readonly string[]; masked_fields?: readonly string[] },
  field: string,
): RestrictionKind | undefined {
  if (record.hidden_fields?.includes(field) === true) return 'hidden';
  if (record.masked_fields?.includes(field) === true) return 'masked';
  return undefined;
}
