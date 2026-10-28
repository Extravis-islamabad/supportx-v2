import { App } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  isOwnSettingsVersion,
  useIncidentCatalogue,
  useIncidentSettingsChange,
  type IncidentCatalogue,
  type IncidentTemplate,
  type IncidentScale,
  type Labels,
  type PickList,
  type SettingsChange,
} from '@supportx/api-client';
import {
  describeError,
  markHandled,
  reportError,
  useAppearance,
  useConflict,
  useLabel,
  type ConflictDialogProps,
} from '@supportx/ui';

import { scaleLabel, statusLabel } from '../../incidents/labels';

// Logic shared by the incident settings screens (components live in their own files).
type Translate = ReturnType<typeof useLabel>;

/** Problems of one save, translated, for the dialog that made it (never only in a log). */
export function fieldMessages(t: Translate, error: unknown): string[] {
  if (!(error instanceof ApiError) || error.status !== 422) return [];
  return error.fieldErrors.map((f) => t(f.message_key, f.params ?? {}));
}

/**
 * A refusal's words for the dialog or form that made it (QA WP-029 BUG-02): its field problems
 * (`fields`, already translated) or else its own message, marked as shown so no toast repeats
 * it. Empty for a conflict or a real failure (an outage), which the caller reports as before.
 */
export function refusalMessages(t: Translate, error: unknown, fields: string[]): string[] {
  if (!(error instanceof ApiError) || !error.isRefusal || error.isConflict) return [];
  markHandled(error);
  if (fields.length > 0) return fields;
  const { title, detail } = describeError(error, t);
  return detail === undefined ? [title] : [title, detail];
}

// The incident settings by the names their screens give them (the history's field codes).
const SETTING_NAMES: Record<string, string> = {
  prefix: 'settings.prefix',
  next_number: 'settings.next_number',
  default_impact: 'settings.default_impact',
  default_urgency: 'settings.default_urgency',
  default_priority: 'settings.default_priority',
  auto_status_on_assign: 'settings.auto_status_on_assign',
  keep_following_on_handover: 'settings.keep_following',
  first_response_on: 'settings.first_response_on',
  // Whole parts, when the dialog compares two versions itself.
  statuses: 'settings.statuses',
  transitions: 'settings.reason_prompts',
  scales: 'settings.section.priority',
  matrix: 'settings.matrix',
  reasons: 'settings.section.reasons',
  levels: 'pick_list.level',
  closure_codes: 'pick_list.closure_code',
};
const SCALES = new Set<string>(['impact', 'urgency', 'priority']);

/**
 * A changed incident setting in words, from its field code (`prefix`, `status.<code>.colour`,
 * `matrix.<impact>.<urgency>`, `<list>.<code>`), for the conflict dialog (QA WP-029 BUG-05).
 */
export function settingName(
  t: Translate,
  catalogue: IncidentCatalogue | undefined,
  field: string,
  locale: string,
): string {
  const named = SETTING_NAMES[field];
  if (named !== undefined) return t(named);
  const [head = '', first = '', second = ''] = field.split('.');
  if (head === 'status') return statusLabel(t, catalogue, first, locale);
  if (head === 'transition') {
    return t('settings.reason_for', {
      action: t(`work_item_action.${second}`),
      status: statusLabel(t, catalogue, first, locale),
    });
  }
  if (head === 'matrix') {
    return t('settings.matrix_cell', {
      impact: scaleLabel(t, catalogue, 'impact', first, locale),
      urgency: scaleLabel(t, catalogue, 'urgency', second, locale),
    });
  }
  if (SCALES.has(head)) return scaleLabel(t, catalogue, head as IncidentScale, first, locale);
  // A pick list's value or its order (`level.l2`, `cancel.order`).
  return t(`pick_list.${head}`);
}

/**
 * The settings a person changes, for the conflict dialog to compare: not the next free number
 * (it moves with every new incident) nor the actions (they follow the statuses).
 */
function settingsView(catalogue: IncidentCatalogue | undefined): object | undefined {
  if (catalogue === undefined) return undefined;
  return Object.fromEntries(
    Object.entries(catalogue).filter(([key]) => key !== 'next_number' && key !== 'actions'),
  );
}

/**
 * One settings write with the shared outcomes (REQ-WI-009): success message; a conflict opens
 * the shared conflict dialog (who, when, which settings: QA WP-029 BUG-05); field problems, and any other
 * refusal (a rule, a limit), go back to the caller's dialog, once (QA WP-029 BUG-02); anything
 * else (an outage) is reported.
 */
export function useSettingsSave() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const change = useIncidentSettingsChange();
  const catalogue = useIncidentCatalogue();
  const conflict = useConflict();
  // The save the conflict stopped: "Keep my changes" sends it again on the saved version; and
  // the settings at the version it was based on, for the dialog to compare with the live ones.
  const [stopped, setStopped] = useState<{
    next: SettingsChange;
    onDone?: () => void;
    opened?: IncidentCatalogue;
  }>();
  // Every version this screen has shown, so a stale save can be compared with its own version.
  const [seen, setSeen] = useState<ReadonlyMap<number, IncidentCatalogue>>(new Map());
  const shown = catalogue.data;
  if (shown !== undefined && !seen.has(shown.version)) {
    setSeen(new Map(seen).set(shown.version, shown));
  }
  const [problems, setProblems] = useState<string[]>([]);
  // The same problems by field ("prefix", "next_number"), for forms that show them in place (C1).
  const [byField, setByField] = useState<Record<string, string>>({});
  /**
   * `version`: the catalogue version the form or dialog started from (useDraft's base,
   * useOpenedVersion). A save from an older version is refused, never applied over someone
   * else's change (QA WP-026 BUG-01); without it, the version on screen now is sent.
   */
  const save = (next: SettingsChange, onDone?: () => void, version?: number) => {
    const basedOn = version ?? shown?.version;
    setProblems([]);
    setByField({});
    change.mutate(
      { change: next, version },
      {
        onSuccess: () => {
          void message.success(t('settings.saved'));
          onDone?.();
        },
        onError: (error) => {
          // The catalogue is fetched again by the mutation; the dialog names who changed what.
          if (conflict.take(error)) {
            setStopped({
              next,
              onDone,
              opened: basedOn === undefined ? undefined : seen.get(basedOn),
            });
            return;
          }
          const fields = fieldMessages(t, error);
          if (fields.length > 0) {
            markHandled(error);
            setProblems(fields);
            if (error instanceof ApiError) {
              setByField(
                Object.fromEntries(
                  error.fieldErrors.map((f) => [
                    f.field.replace(/^body\./, ''),
                    t(f.message_key, f.params ?? {}),
                  ]),
                ),
              );
            }
            return;
          }
          const refused = refusalMessages(t, error, []);
          if (refused.length > 0) {
            setProblems(refused);
            return;
          }
          reportError(error);
        },
      },
    );
  };
  /**
   * Props of the screen's <ConflictDialog>. "Reload" drops the edits the way a successful save
   * does (`onDone`: reset the form or close its dialog); "Keep my changes" saves them again.
   */
  const conflictDialog: ConflictDialogProps = {
    open: conflict.open,
    error: conflict.error,
    fieldLabel: (field) => settingName(t, catalogue.data, field, locale),
    opened: settingsView(stopped?.opened),
    latest: settingsView(catalogue.data),
    onReload: () => {
      conflict.clear();
      stopped?.onDone?.();
      setStopped(undefined);
    },
    onKeepMine: () => {
      conflict.clear();
      if (stopped !== undefined) {
        save(stopped.next, stopped.onDone, conflict.latestVersion ?? catalogue.data?.version);
      }
      setStopped(undefined);
    },
  };
  return {
    save,
    conflictDialog,
    pending: change.isPending,
    problems,
    byField,
    clear: () => {
      setProblems([]);
      setByField({});
    },
  };
}

/** Translations with blanks dropped; null when nothing is left (back to the shipped name). */
export function cleanLabels(labels: Labels): Labels | null {
  const kept = Object.fromEntries(
    Object.entries(labels)
      .map(([k, v]) => [k, v.trim()] as const)
      .filter(([, v]) => v !== ''),
  );
  return Object.keys(kept).length === 0 ? null : kept;
}

/**
 * A local copy of some settings for a form. When the saved settings change (here or elsewhere,
 * live) the copy follows, unless the admin has unsaved edits: then they are told, and choose.
 * (Adjusted while rendering, as React recommends for state derived from a changing prop.)
 */
export function useDraft<T>(source: T, version: number) {
  const [state, setState] = useState({ draft: source, base: version, dirty: false });
  if (version !== state.base && !state.dirty) {
    setState({ draft: source, base: version, dirty: false });
  } else if (version !== state.base && isOwnSettingsVersion(version)) {
    // This tab saved another part of the settings (QA BUG-02): not someone else's change.
    setState({ ...state, base: version });
  }
  return {
    draft: state.dirty || version === state.base ? state.draft : source,
    // The version the draft is based on: sent with the save (QA WP-026 BUG-01).
    base: state.dirty ? state.base : version,
    dirty: state.dirty,
    stale: state.dirty && version !== state.base,
    edit: (next: T) => {
      setState({ draft: next, base: state.base, dirty: true });
    },
    reset: () => {
      setState({ draft: source, base: version, dirty: false });
    },
  };
}

/**
 * The catalogue version when a dialog opened: its save sends it, so a change saved elsewhere
 * meanwhile is refused instead of overwritten (QA WP-026 BUG-01).
 */
export function useOpenedVersion(open: boolean, version: number): number {
  const [opened, setOpened] = useState<number | null>(null);
  if (open && opened === null) setOpened(version);
  if (!open && opened !== null) setOpened(null);
  return opened ?? version;
}

/** The shipped label key of a seeded value of `list`. */
export function shippedKey(list: PickList, code: string): string {
  if (list === 'level') return `level.${code}`;
  if (list === 'closure_code') return `closure_code.${code}`;
  return `reason.${list}.${code}`;
}

/** Problems of a template save, each named by its field ("Category: ..."). */
export function templateProblems(
  t: ReturnType<typeof useLabel>,
  error: unknown,
  // Names fields the labels package does not know (custom fields, WP-026).
  nameOf: (field: string) => string = (field) => t(`work_item.field.${field}`),
): string[] {
  if (!(error instanceof ApiError) || error.status !== 422) return [];
  return error.fieldErrors.map((f) => {
    const message = t(f.message_key, f.params ?? {});
    const match = /^body\.(fields|defaults)\.([a-z_.]+)$/.exec(f.field);
    if (match === null) return message;
    const field = nameOf(match[2] ?? '');
    return t(match[1] === 'defaults' ? 'templates.problem_default' : 'templates.problem_field', {
      field,
      message,
    });
  });
}

// A template's parts by the names this editor gives them (the history's field codes).
const TEMPLATE_PARTS: Record<string, string> = {
  labels: 'settings.name',
  description: 'templates.description',
  group_name: 'templates.group',
  for_requesters: 'templates.for_requesters',
  fields: 'templates.fields',
  field_rules: 'templates.fields',
  custom_fields: 'templates.fields',
  defaults: 'templates.starting_values',
  is_default: 'templates.default',
  disabled: 'templates.disabled',
};

/** What a person edits of a template, for the conflict dialog (QA WP-029 BUG-05). */
export function templateView(template: IncidentTemplate | null | undefined): object | undefined {
  if (template == null) return undefined;
  const all = template as unknown as Record<string, unknown>;
  return Object.fromEntries(
    Object.keys(TEMPLATE_PARTS)
      .filter((part) => part in all)
      .map((part) => [part, all[part]]),
  );
}

/** A template's part in words. */
export function useTemplatePartName(): (field: string) => string {
  const t = useLabel();
  return (field) => t(TEMPLATE_PARTS[field] ?? 'templates.field');
}
