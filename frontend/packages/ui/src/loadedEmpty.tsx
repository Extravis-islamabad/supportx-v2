import type { ReactNode } from 'react';

import { EmptyText } from './EmptyText';

/**
 * A list's empty text, only once its first answer is in (QA fix-round, 2026-11-10): while it
 * loads the table shows its spinner alone, never "No incidents in this view" beneath it.
 * `locale={{ emptyText: loadedEmpty(list.isPending, t('incidents.empty')) }}`.
 */
export function loadedEmpty(loading: boolean, text: ReactNode): ReactNode {
  return loading ? <span data-testid="empty-loading" /> : <EmptyText>{text}</EmptyText>;
}
