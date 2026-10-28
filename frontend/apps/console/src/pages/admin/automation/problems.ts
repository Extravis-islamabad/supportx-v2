import { useCallback, useMemo, useState } from 'react';

import { ApiError } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

/** One problem the server found in an editor, at its field (QA WP-029 BUG-03). */
export interface EditorProblem {
  /** Field path in the body, e.g. `name`, `actions.0.field`, `conditions.and.1.value`. */
  path: string;
  /** Where it is, as people read it: "Name", "Action 1", "Condition 2". */
  where: string;
  message: string;
}

type Translate = ReturnType<typeof useLabel>;

const LISTS = /^(actions|after_actions|group_ids)\.(\d+)/;
const CONDITION = /^conditions(?:\.(?:and|or))*\.(\d+)/;
// Body fields with an editor label of their own; the rest are named under automation.problem_field.
const OWN_LABEL = new Set(['name', 'description', 'events', 'state', 'conditions', 'actions']);

/** Where a body path is in the editor, in words. */
export function whereOf(t: Translate, path: string): string {
  const listed = LISTS.exec(path);
  if (listed !== null) {
    return t(`automation.problem.${listed[1] ?? 'actions'}`, { n: Number(listed[2]) + 1 });
  }
  const condition = CONDITION.exec(path);
  if (condition !== null) {
    return t('automation.problem.condition', { n: Number(condition[1]) + 1 });
  }
  const head = path.split('.')[0] ?? '';
  return OWN_LABEL.has(head)
    ? t(`automation.field_${head}`)
    : t(`automation.problem_field.${head}`);
}

/** A 422's problems, each with the field it is about; empty for any other error. */
export function editorProblems(t: Translate, error: unknown): EditorProblem[] {
  if (!(error instanceof ApiError) || error.status !== 422) return [];
  if (error.fieldErrors.length === 0) {
    return [{ path: '', where: '', message: t(error.messageKey, error.params) }];
  }
  return error.fieldErrors.map((f) => {
    const path = f.field.replace(/^body\./, '');
    return { path, where: whereOf(t, path), message: t(f.message_key, f.params ?? {}) };
  });
}

/** Whether a problem is at `prefix` or inside it (`actions.0` covers `actions.0.value`). */
export function isAt(problems: readonly EditorProblem[], prefix: string): boolean {
  return problems.some((p) => p.path === prefix || p.path.startsWith(`${prefix}.`));
}

/** Whether condition row `index` has a problem (conditions are one flat list in the editor). */
export function conditionAt(problems: readonly EditorProblem[], index: number): boolean {
  return problems.some((p) => CONDITION.exec(p.path)?.[1] === String(index));
}

export interface EditorProblems {
  problems: EditorProblem[];
  /** Take the problems of a failed save; true when there were any (shown here). */
  take: (error: unknown) => boolean;
  clear: () => void;
  /** Ant Design `status` for an input at `prefix`. */
  status: (prefix: string) => 'error' | undefined;
}

export function useEditorProblems(): EditorProblems {
  const t = useLabel();
  const [problems, setProblems] = useState<EditorProblem[]>([]);
  const take = useCallback(
    (error: unknown) => {
      const found = editorProblems(t, error);
      setProblems(found);
      return found.length > 0;
    },
    [t],
  );
  const clear = useCallback(() => {
    setProblems([]);
  }, []);
  return useMemo(
    () => ({
      problems,
      take,
      clear,
      status: (prefix: string) => (isAt(problems, prefix) ? 'error' : undefined),
    }),
    [problems, take, clear],
  );
}
