import { createContext, useContext, useEffect } from 'react';

/**
 * Where the user is (product owner, 2026-10-28): the header shows breadcrumbs of the current page
 * ("Incidents › INC-42", the record's desk first when ESM is on) instead of a fixed app name, and
 * the browser tab says the same, newest first ("INC-42 · Incidents · SupportX").
 */

export interface Crumb {
  /** Words already in the user's language (a label, a display ID, a record's name). */
  label: string;
  /** Where it leads; the last crumb (the page itself) has none. */
  path?: string;
}

export interface CrumbState {
  crumbs: Crumb[] | null;
  setCrumbs: (crumbs: Crumb[] | null) => void;
}

export const CrumbContext = createContext<CrumbState>({ crumbs: null, setCrumbs: () => undefined });

/**
 * A page says where it is ("Incidents › INC-42"). Without it, the layout's section crumb is used.
 * Pass a stable value (or null while the record loads); the page's crumbs go when it does.
 */
export function usePageCrumbs(crumbs: Crumb[] | null): void {
  const { setCrumbs } = useContext(CrumbContext);
  const key = crumbs === null ? null : JSON.stringify(crumbs);
  useEffect(() => {
    setCrumbs(key === null ? null : (JSON.parse(key) as Crumb[]));
    return () => {
      setCrumbs(null);
    };
  }, [key, setCrumbs]);
}

/** The crumbs in effect: the page's own, else the section's. */
export function useCurrentCrumbs(fallback: Crumb[]): Crumb[] {
  return useContext(CrumbContext).crumbs ?? fallback;
}

/** The browser tab: the crumbs newest first, then the product ("INC-42 · Incidents · SupportX"). */
export function documentTitle(crumbs: Crumb[], product: string): string {
  return [...crumbs.map((c) => c.label).reverse(), product].filter(Boolean).join(' · ');
}

export function useDocumentTitle(crumbs: Crumb[], product: string): void {
  const title = documentTitle(crumbs, product);
  useEffect(() => {
    document.title = title;
  }, [title]);
}
