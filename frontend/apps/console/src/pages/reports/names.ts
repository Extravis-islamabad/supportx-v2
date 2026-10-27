import {
  useCustomFields,
  useIncidentCatalogue,
  useIncidentCategories,
  useStructure,
  useUsers,
  type CustomField,
  type ReportField,
  type ReportGroup,
  type ReportMeasure,
  type ReportResult,
} from '@supportx/api-client';
import { useLabels } from '@supportx/labels';
import type { FilterChoice } from '@supportx/forms';
import { useAppearance, useDateTime } from '@supportx/ui';

import { choiceName, fieldName } from '../customFields/values';
import { labelled, levelLabel, statusLabel } from '../incidents/labels';

// Words for everything a report shows (rule d): grouping values (codes, admin values, records
// by name, date buckets), field names and measure values. Report results carry codes and ids;
// the names come from the lists the console already has, so no code ever reaches the screen.

const SHIPPED_FIELD_LABELS = new Set([
  'requester_id',
  'channel',
  'site_id',
  'group_id',
  'technician_id',
  'category_id',
  'impact',
  'urgency',
  'priority',
  'priority_source',
  'status',
  'resolved_at',
  'closed_at',
  'reopen_count',
  'reassignment_count',
  'first_responded_at',
  'level',
  'template_id',
  'department_id',
]);

/** Fields a report on incidents offers in its filter and grouping, in this order. */
export const INCIDENT_REPORT_FIELDS = [
  'status_category',
  'status',
  'priority',
  'impact',
  'urgency',
  'channel',
  'group_id',
  'technician_id',
  'site_id',
  'department_id',
  'requester_id',
  'category_id',
  'level',
  'created_at',
  'resolved_at',
  'closed_at',
  'first_responded_at',
  'reopen_count',
  'reassignment_count',
] as const;

export interface ReportWords {
  /** A field's name: custom fields by their label, others by the shipped label. */
  field: (name: string) => string;
  /** One grouping value as people read it ("not set" for empty). */
  key: (group: ReportGroup, key: unknown) => string;
  /** A measure's name and help text. */
  measure: (entity: string, code: string) => { name: string; help: string };
  /** A value in the measure's unit (count, duration, percent, number), in the UI language. */
  value: (measure: Pick<ReportMeasure, 'unit'>, value: number | null | undefined) => string;
  /**
   * The values a filter on `field` offers, named; undefined when the field has no fixed list
   * (people are picked by grouping, not typed as ids).
   */
  choices: (field: ReportField) => FilterChoice[] | undefined;
  /** Records of these kinds can be named (people, units, categories): their lists are loaded. */
  ready: boolean;
  customFields: CustomField[];
}

function userIds(result: ReportResult | undefined): string[] {
  if (result === undefined) return [];
  const ids = new Set<string>();
  result.groups.forEach((group, index) => {
    if (group.reference !== 'user') return;
    for (const row of result.rows) {
      const key = row.keys[index];
      if (typeof key === 'string') ids.add(key);
    }
  });
  return [...ids].sort().slice(0, 100); // the filter DSL takes 100 values; top-N reports fit
}

/** Names for one report result (and for the field pickers). */
export function useReportWords(result?: ReportResult): ReportWords {
  const t = useLabels();
  const { locale } = useAppearance();
  const dates = useDateTime();
  const catalogue = useIncidentCatalogue();
  const categories = useIncidentCategories();
  const custom = useCustomFields('incident');
  const groups = useStructure('groups', true, true);
  const sites = useStructure('sites', true, true);
  const departments = useStructure('departments', true, true);
  const desks = useStructure('desks', true, true);
  const ids = userIds(result);
  const users = useUsers(
    { filter: { field: 'id', op: 'in', value: ids }, limit: 100 },
    ids.length > 0,
  );
  const people = new Map(
    (users.data?.pages ?? []).flatMap((page) => page.items).map((u) => [u.id, u.display_name]),
  );
  const customFields = custom.data ?? [];
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
  const percent = new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1 });

  const named = (rows: { id: string; name: string }[] | undefined, id: string) =>
    rows?.find((row) => row.id === id)?.name;

  const reference = (kind: string | null | undefined, id: string): string | undefined => {
    switch (kind) {
      case 'group':
        return named(groups.data, id);
      case 'site':
        return named(sites.data, id);
      case 'department':
        return named(departments.data, id);
      case 'desk': {
        const desk = desks.data?.find((d) => d.id === id);
        return desk ? labelled(desk.labels, locale, () => t(`desk.${desk.code}`)) : undefined;
      }
      case 'category': {
        const category = categories.data?.find((c) => c.id === id);
        return category
          ? labelled(category.labels, locale, () => t(`work_item_category.${category.code ?? ''}`))
          : undefined;
      }
      case 'user':
        return people.get(id);
      default:
        return undefined;
    }
  };

  const bucket = (group: ReportGroup, key: string): string => {
    switch (group.bucket) {
      case 'age':
        return t(`age_bucket.${key}`);
      case 'day':
        return dates.formatDay(key.slice(0, 10));
      case 'week':
        return t('reports.week_of', { day: dates.formatDay(key.slice(0, 10)) });
      case 'month':
        return new Intl.DateTimeFormat(locale, {
          month: 'long',
          year: 'numeric',
          timeZone: 'UTC',
        }).format(new Date(`${key.slice(0, 10)}T00:00:00Z`));
      case 'quarter': {
        const month = Number(key.slice(5, 7));
        return t('reports.quarter_of', {
          quarter: Math.floor((month - 1) / 3) + 1,
          year: key.slice(0, 4),
        });
      }
      case 'year':
        return key.slice(0, 4);
      default:
        return dates.formatDay(key.slice(0, 10));
    }
  };

  const key = (group: ReportGroup, value: unknown): string => {
    if (value === null || value === undefined || value === '') return t('reports.not_set');
    const text = typeof value === 'string' ? value : JSON.stringify(value);
    if (group.kind === 'datetime') return bucket(group, text);
    if (group.kind === 'code') return t(`${group.label_prefix ?? group.field}.${text}`);
    if (group.kind === 'boolean') return t(value === true ? 'filter.yes' : 'filter.no');
    if (group.kind === 'number') return number.format(Number(value));
    if (group.kind === 'reference')
      return reference(group.reference, text) ?? t('reports.unknown_value');
    // Admin-defined codes: statuses, levels and custom choices carry their own labels.
    if (group.field === 'status') return statusLabel(t, catalogue.data, text, locale);
    if (group.field === 'level') return levelLabel(t, catalogue.data, text, locale);
    const customField = customFields.find((f) => `custom.${f.key}` === group.field);
    return customField ? choiceName(t, customField, text, locale) : t('reports.unknown_value');
  };

  const field = (name: string): string => {
    if (name.startsWith('custom.')) {
      const customField = customFields.find((f) => `custom.${f.key}` === name);
      return customField ? fieldName(customField, locale) : t('reports.unknown_value');
    }
    return SHIPPED_FIELD_LABELS.has(name)
      ? t(`work_item.field.${name}`)
      : t(`report_field.${name}`);
  };

  const duration = (seconds: number): string => {
    const minutes = Math.round(seconds / 60);
    const days = Math.floor(minutes / 1440);
    const hours = Math.floor((minutes % 1440) / 60);
    const rest = minutes % 60;
    if (days > 0) return t('reports.duration_days', { days, hours });
    if (hours > 0) return t('reports.duration_hours', { hours, minutes: rest });
    return t('reports.duration_minutes', { minutes: rest });
  };

  const choices = (input: ReportField): FilterChoice[] | undefined => {
    const group = input.dimension;
    if (input.values.length > 0) {
      const asGroup: ReportGroup = group ?? {
        field: input.name,
        kind: 'code',
        label_prefix: input.name,
        reference: null,
        bucket: null,
      };
      return input.values.map((value) => ({ value, label: key(asGroup, value) }));
    }
    if (group?.kind !== 'reference') return undefined;
    const rows: { id: string; disabled?: boolean }[] | undefined = {
      group: groups.data,
      site: sites.data,
      department: departments.data,
      desk: desks.data,
      category: categories.data,
    }[group.reference ?? ''];
    return rows?.map((row) => ({ value: row.id, label: reference(group.reference, row.id) ?? '' }));
  };

  return {
    field,
    key,
    choices,
    measure: (entity, code) => ({
      name: t(`measure.${entity}.${code}`),
      help: t(`measure.${entity}.${code}.help`),
    }),
    value: (measure, value) => {
      if (value === null || value === undefined) return t('reports.no_value');
      switch (measure.unit) {
        case 'seconds':
          return duration(value);
        case 'percent':
          return percent.format(value / 100);
        default:
          return number.format(value);
      }
    },
    ready: !groups.isLoading && !sites.isLoading && !categories.isLoading && !users.isLoading,
    customFields,
  };
}
