/**
 * The problem with a typed number, as people read it, or null (QA WP-026 BUG-03). Number inputs
 * never clamp or round what was typed: they show this message at the field and the save waits.
 */
export function numberProblem(
  t: (key: string, params?: Record<string, string | number>) => string,
  value: number | string | null | undefined,
  rules: { min?: number | string | null; max?: number | string | null; whole?: boolean },
): string | null {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return t('errors.field.invalid_value');
  if (rules.whole === true && !Number.isInteger(number)) {
    return t('errors.field.whole_number_required');
  }
  if (rules.min != null && number < Number(rules.min)) {
    return t('errors.field.below_minimum', { min: String(rules.min) });
  }
  if (rules.max != null && number > Number(rules.max)) {
    return t('errors.field.above_maximum', { max: String(rules.max) });
  }
  return null;
}
