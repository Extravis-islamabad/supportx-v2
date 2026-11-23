import { useMemo } from 'react';

import { stepNames } from '@supportx/flow';
import { useLabel } from '@supportx/ui';

// Steps by name, never by their internal id (QA 2026-11-11 F-07; rule 5d): the type's label,
// numbered when the type repeats ("Add a note 2"). An id the definition no longer has (a run on an
// older version) is "a step of an earlier version", never the id itself.

type Translate = (key: string, params?: Record<string, string | number>) => string;

/** The steps' names in a definition (or a version's step list). */
export function useStepName(
  nodes: readonly { id: string; type: string }[],
): (id: string | null | undefined) => string {
  const t = useLabel();
  const names = useMemo(() => stepNames(nodes), [nodes]);
  return (id) => nameOf(t, names, id);
}

/** The same, outside a component's top level (inside a list's map). */
export function namer(
  t: Translate,
  nodes: readonly { id: string; type: string }[],
): (id: string | null | undefined) => string {
  const names = stepNames(nodes);
  return (id) => nameOf(t, names, id);
}

function nameOf(
  t: Translate,
  names: ReadonlyMap<string, { type: string; n?: number }>,
  id: string | null | undefined,
): string {
  if (id === null || id === undefined || id === '') return '';
  const found = names.get(id);
  if (found === undefined) return t('workflows.step_unknown');
  const type = t(`workflow_node_type.${found.type}`);
  return found.n === undefined ? type : t('workflows.step_numbered', { type, n: found.n });
}
