import { useMemo } from 'react';

import {
  useCustomFields,
  useIncidentCatalogue,
  useIncidentCategories,
  useIncidentHistory,
  useIncidentTemplates,
  useProblemCatalogue,
  useProblemCategories,
  useProblemTemplates,
  useUnits,
  type IncidentHistoryEntry,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { useAccess, useAppearance, useDateTime, useLabel } from '@supportx/ui';

import { fieldName, useCustomValueText } from '../customFields/values';
import { useAutomationWhy, useRequesterActionWhy } from './automationWhy';
import {
  categoryPath,
  closureCodeLabel,
  levelLabel,
  reasonValueLabel,
  scaleLabel,
  statusLabel,
  templateLabel,
} from './labels';

// The words of an incident's history (REQ-WI-003/004), shared by the History tab and the
// conversation timeline's quiet event lines (UI pass 2): field names, values as labels, names
// and local times (never raw codes or IDs, rule d), and why it happened.

type Change = IncidentHistoryEntry['changes'][number];

/** The requester's own act: shown as the why-line, not as a changed field (QA BUG-03). */
export const REQUESTER_ACTION = 'requester_action';

const CODED: Record<string, string> = {
  priority_source: 'priority_source',
  channel: 'work_item_channel',
  follow_reason: 'follow_reason',
  conversation_entry: 'conversation_entry',
  note_visibility: 'visibility',
  'task.status': 'task_status', // WP-020e
  'task.priority': 'task_priority',
  first_response_sla_state: 'sla_target_state', // WP-025
  resolution_sla_state: 'sla_target_state',
};
const TIMES = new Set([
  'resolved_at',
  'closed_at',
  'last_reopened_at',
  'first_responded_at',
  'resolution_notified_at',
  'task.due_at',
  'first_response_due_at', // WP-025
  'resolution_due_at',
]);
// Rich text and references with no words of their own: "changed", never the HTML or an ID.
const CHANGED_ONLY = new Set([
  'description',
  'resolution',
  'follows_id',
  'task.position',
  'sla_policy_id', // WP-025: the panel names the policy
]);
const PEOPLE = new Set([
  'requester_id',
  'on_behalf_of_id',
  'technician_id',
  'follower',
  'follower_access',
  'task.owner_id',
]);
// Flags: "not set" reads "No", not "(empty)".
const FLAGS = new Set(['handed_over_out_of_reach']);

export type HistoryActors = 'all' | 'people' | 'automation';

/** The history of incident `id` and how to say each change. */
export function useHistoryWords(
  id: string,
  actors: HistoryActors = 'all',
  base: 'incidents' | 'problems' = 'incidents',
  enabled = true,
) {
  const t = useLabel();
  const listFormat = useListFormat();
  const { locale } = useAppearance();
  const dates = useDateTime();
  const { can } = useAccess();
  // A problem's history reads its own type's lists (WP-044c); both hooks run, one enabled.
  const isProblem = base === 'problems';
  const history = useIncidentHistory(id, actors, enabled, base);
  const incidentCatalogue = useIncidentCatalogue(!isProblem);
  const problemCatalogue = useProblemCatalogue(isProblem);
  const catalogue = isProblem ? problemCatalogue : incidentCatalogue;
  const incidentCategories = useIncidentCategories(!isProblem);
  const problemCategories = useProblemCategories(isProblem);
  const categories = isProblem ? problemCategories : incidentCategories;
  const incidentTemplates = useIncidentTemplates(!isProblem);
  const problemTemplates = useProblemTemplates(isProblem);
  const templates = isProblem ? problemTemplates : incidentTemplates;
  // Removed fields too: their old values stay in the history (REQ-INC-014 AC4).
  const customFields = useCustomFields(isProblem ? 'problem' : 'incident', true);
  const customText = useCustomValueText();
  const customField = (name: string) =>
    name.startsWith('custom.')
      ? customFields.data?.find((f) => `custom.${f.key}` === name)
      : undefined;
  const fieldText = (name: string) => {
    if (!name.startsWith('custom.')) return t(`work_item.field.${name}`);
    const found = customField(name);
    return found === undefined ? t('custom_fields.unknown_field') : fieldName(found, locale);
  };
  const sites = useUnits('sites', can('sites.view'));
  const groups = useUnits('groups', can('groups.view'));
  const units = useMemo(
    () => new Map([...(sites.data ?? []), ...(groups.data ?? [])].map((u) => [u.id, u.name])),
    [sites.data, groups.data],
  );
  const entries = history.data?.pages.flatMap((page) => page.items) ?? [];
  // People named in changed values, from every page (QA BUG-03).
  const people = useMemo(
    () =>
      Object.assign({}, ...(history.data?.pages.map((page) => page.people) ?? [])) as Record<
        string,
        { display_name: string; email: string } | undefined
      >,
    [history.data],
  );

  const why = useAutomationWhy();
  const requesterWhy = useRequesterActionWhy();
  /** Why it happened: the automation that did it, or what the requester did (QA BUG-03). */
  const whyText = (entry: IncidentHistoryEntry) =>
    entry.automation !== null
      ? why(entry.automation, people)
      : requesterWhy(entry.changes.find((c) => c.field === REQUESTER_ACTION)?.new);

  const valueText = (change: Change, value: unknown): string => {
    if (FLAGS.has(change.field) && (value === null || value === undefined)) return t('history.no');
    if (value === null || value === undefined || value === '') return t('history.empty');
    const custom = customField(change.field);
    if (custom !== undefined) {
      return (
        customText(custom, value, people as Record<string, { display_name: string }>) ||
        t('history.empty')
      );
    }
    if (change.field.startsWith('custom.')) return t('history.changed');
    if (change.field === 'status' && typeof value === 'string') {
      return statusLabel(t, catalogue.data, value, locale);
    }
    if (
      (change.field === 'priority' || change.field === 'impact' || change.field === 'urgency') &&
      typeof value === 'string'
    ) {
      return scaleLabel(t, catalogue.data, change.field, value, locale);
    }
    if (change.field === 'level' && typeof value === 'string') {
      return levelLabel(t, catalogue.data, value, locale);
    }
    if (change.field === 'closure_code' && typeof value === 'string') {
      return closureCodeLabel(t, catalogue.data, value, locale);
    }
    if (change.field === 'template_id' && typeof value === 'string') {
      const found = templates.data?.find((x) => x.id === value);
      return found === undefined ? t('history.changed') : templateLabel(t, found, locale);
    }
    // WP-025: an escalation level that ran ("resolution:2").
    if (change.field === 'sla_escalation' && typeof value === 'string') {
      const [target = '', level = ''] = value.split(':');
      return t('history.sla_escalation', {
        target: t(`sla_target_kind.${target}`),
        level: Number(level),
      });
    }
    const prefix = CODED[change.field];
    if (prefix !== undefined && typeof value === 'string') return t(`${prefix}.${value}`);
    if (
      (change.field === 'status_reason_code' || change.field === 'assignment_reason') &&
      typeof value === 'string'
    ) {
      return reasonValueLabel(
        t,
        catalogue.data,
        value,
        locale,
        change.field === 'assignment_reason' ? 'reassign' : null,
      );
    }
    if (TIMES.has(change.field) && typeof value === 'string') return dates.format(value);
    if (change.field === 'category_id' && typeof value === 'string') {
      return categoryPath(t, categories.data ?? [], value, locale) || t('history.changed');
    }
    // WP-020e parts: a worklog as person, type and time; a link by its kind only (the other
    // record may be one this reader cannot see, REQ-INC-084 AC3).
    if (change.field === 'worklog' && typeof value === 'object') {
      const log = value as { owner_id?: string; worklog_type?: string; minutes?: number };
      return t('incidents.worklogs.line', {
        person: people[log.owner_id ?? '']?.display_name ?? t('incidents.unknown_value'),
        type: t(`worklog_type.${log.worklog_type ?? 'other'}`),
        duration: t('incidents.worklogs.minutes', { minutes: log.minutes ?? 0 }),
      });
    }
    if (change.field === 'link' && typeof value === 'object') {
      return t(`link_kind.${(value as { kind?: string }).kind ?? 'related'}`);
    }
    if (
      (change.field === 'site_id' ||
        change.field === 'group_id' ||
        change.field === 'task.group_id') &&
      typeof value === 'string'
    ) {
      return units.get(value) ?? t('history.changed');
    }
    if (PEOPLE.has(change.field) && typeof value === 'string') {
      return people[value]?.display_name ?? t('history.changed');
    }
    if (CHANGED_ONLY.has(change.field)) return t('history.changed');
    if (typeof value === 'boolean') return t(value ? 'history.yes' : 'history.no');
    if (Array.isArray(value))
      return value.length === 0 ? t('history.empty') : listFormat(value.map(String));
    if (typeof value === 'string' || typeof value === 'number') return String(value);
    return t('history.changed');
  };

  return { history, entries, people, fieldText, valueText, whyText };
}
