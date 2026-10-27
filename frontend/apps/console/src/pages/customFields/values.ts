import type { CustomField, IncidentPerson } from '@supportx/api-client';
import { useAppearance, useDateTime, useLabel } from '@supportx/ui';

// Custom field names and values as text (WP-026): shared by forms, records, lists, history.

type Labels = Record<string, string> | null | undefined;

/** Admin text in the user's language, else English (the API requires English). */
export function localized(labels: Labels, locale: string): string {
  return labels?.[locale] ?? labels?.en ?? '';
}

export function fieldName(field: Pick<CustomField, 'labels'>, locale: string): string {
  return localized(field.labels, locale);
}

/** A choice's label; a code the field no longer has reads "Unknown value". */
export function choiceName(
  t: (key: string, params?: Record<string, string>) => string,
  field: CustomField,
  code: string,
  locale: string,
): string {
  const choice = field.choices.find((c) => c.code === code);
  if (choice === undefined) return t('custom_fields.unknown_value');
  const name = localized(choice.labels, locale);
  return choice.retired ? t('custom_fields.retired_value', { name }) : name;
}

export const TEXT_MAX = 250;
export const LONG_TEXT_MAX = 10_000;

/** Whether a custom value counts as filled in. */
export function filled(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === 'string') return value.trim() !== '';
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

/** Only web links open: a value that is not http(s) stays plain text. */
export function safeUrl(value: string): string | null {
  return /^https?:\/\//i.test(value) ? value : null;
}

/** The value as text (history lines, list cells, conflict dialogs). */
export function useCustomValueText() {
  const t = useLabel();
  const { locale } = useAppearance();
  const dates = useDateTime();
  return (
    field: CustomField,
    value: unknown,
    people: Record<string, Pick<IncidentPerson, 'display_name'>> = {},
  ): string => {
    if (!filled(value)) return '';
    switch (field.field_type) {
      case 'yes_no':
        return t(value === true ? 'custom_fields.yes' : 'custom_fields.no');
      case 'choice':
        return choiceName(t, field, String(value), locale);
      case 'multi_choice':
        return (value as string[]).map((c) => choiceName(t, field, c, locale)).join(', ');
      case 'date':
        return dates.formatDay(String(value));
      case 'datetime':
        return dates.format(String(value));
      case 'currency':
        try {
          return new Intl.NumberFormat(locale, {
            style: 'currency',
            currency: field.currency ?? 'USD',
          }).format(Number(value));
        } catch {
          return String(value);
        }
      case 'integer':
      case 'decimal':
        return new Intl.NumberFormat(locale, { maximumFractionDigits: 6 }).format(Number(value));
      case 'person':
        return people[String(value)]?.display_name ?? t('custom_fields.unknown_person');
      default:
        return String(value);
    }
  };
}
