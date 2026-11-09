import { App } from 'antd';
import { useState } from 'react';

import { ApiError, useAssetCatalogueChange, type AssetCatalogueChange } from '@supportx/api-client';
import { reportError, useLabel } from '@supportx/ui';

import { fieldMessages, refusalMessages } from '../incidents/helpers';

// Shared by the asset catalogue tabs (WP-049a).

export type Names = Record<string, string>;

/** A stored name in the screen's language, else English (D-041: names are data). */
export function nameOf(names: Names, locale: string): string {
  return names[locale] ?? names.en ?? '';
}

/**
 * A stable lowercase code for a new row, from its English name. Logic, events and the API use
 * the code; it is never shown (the coordinator's rule for seeded and added rows), so the admin
 * never types one. A name with no Latin letters gets `fallback`; a taken code gets a number.
 */
export function codeFrom(english: string, taken: ReadonlySet<string>, fallback: string): string {
  const slug = english
    .normalize('NFKD')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 32);
  const base = /^[a-z][a-z0-9_]+$/.test(slug) ? slug : fallback;
  let code = base;
  for (let n = 2; taken.has(code); n += 1) code = `${base}_${String(n)}`;
  return code;
}

/**
 * One catalogue write with the shared outcomes: a success message; field problems and other
 * refusals back to the dialog that made them, once; a conflict or an outage is reported (the
 * catalogue refetches on a conflict, so the dialog then shows the other admin's change).
 */
export function useCatalogueSave() {
  const t = useLabel();
  const { message } = App.useApp();
  const change = useAssetCatalogueChange();
  const [problems, setProblems] = useState<string[]>([]);
  const run = (next: AssetCatalogueChange, done?: () => void, conflicted?: () => void) => {
    setProblems([]);
    change.mutate(next, {
      onSuccess: () => {
        void message.success(t('settings.saved'));
        done?.();
      },
      onError: (error) => {
        if (error instanceof ApiError && error.isConflict) conflicted?.();
        const shown = refusalMessages(t, error, fieldMessages(t, error));
        if (shown.length > 0) setProblems(shown);
        else reportError(error);
      },
    });
  };
  return {
    run,
    problems,
    clear: () => {
      setProblems([]);
    },
    pending: change.isPending,
  };
}
