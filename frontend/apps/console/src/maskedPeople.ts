import { useSession } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

/**
 * People's names withheld from a vendor support session whose grant masks names (D-180; names show
 * by default): the API sends an empty name, and every screen shows this labelled stand-in instead. Derived from the session on
 * every render (lane A's #566 review): right on the first render, live when the session changes,
 * and no module state. Null for everyone else, so an empty name stays empty. The one switch, so
 * mention chips can use the same stand-in when Haider decides (the coordinator's condition 4).
 */
export function useHiddenPersonLabel(): string | null {
  const t = useLabel();
  // D-180: names show unless the grant masks them (e-mail and phone are always withheld).
  const masked = useSession().data?.support?.names_masked === true;
  return masked ? t('vendor_support.person_hidden') : null;
}

/** A person's name as shown: the stand-in when the session masks it, else the name itself. */
export function shownName(name: string | null | undefined, hidden: string | null): string {
  if (hidden !== null && (name ?? '') === '') return hidden;
  return name ?? '';
}
