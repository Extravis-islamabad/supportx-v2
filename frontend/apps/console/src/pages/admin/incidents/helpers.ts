import { App } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  isOwnSettingsVersion,
  useIncidentSettingsChange,
  type Labels,
  type PickList,
  type SettingsChange,
} from '@supportx/api-client';
import { reportError, useLabel } from '@supportx/ui';

// Logic shared by the incident settings screens (components live in their own files).
type Translate = ReturnType<typeof useLabel>;

/** Problems of one save, translated, for the dialog that made it (never only in a log). */
export function fieldMessages(t: Translate, error: unknown): string[] {
  if (!(error instanceof ApiError) || error.status !== 422) return [];
  return error.fieldErrors.map((f) => t(f.message_key, f.params ?? {}));
}

/**
 * One settings write with the shared outcomes (REQ-WI-009): success message; a conflict says
 * the settings were changed elsewhere and shows the latest; field problems go back to the
 * caller's dialog; anything else is reported.
 */
export function useSettingsSave() {
  const t = useLabel();
  const { message } = App.useApp();
  const change = useIncidentSettingsChange();
  const [problems, setProblems] = useState<string[]>([]);
  // The same problems by field ("prefix", "next_number"), for forms that show them in place (C1).
  const [byField, setByField] = useState<Record<string, string>>({});
  /**
   * `version`: the catalogue version the form or dialog started from (useDraft's base,
   * useOpenedVersion). A save from an older version is refused, never applied over someone
   * else's change (QA WP-026 BUG-01); without it, the version on screen now is sent.
   */
  const save = (next: SettingsChange, onDone?: () => void, version?: number) => {
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
          if (error instanceof ApiError && error.isConflict) {
            void message.warning(t('settings.changed_elsewhere'));
            return;
          }
          const found = fieldMessages(t, error);
          if (found.length > 0) {
            setProblems(found);
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
          reportError(error);
        },
      },
    );
  };
  return {
    save,
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
