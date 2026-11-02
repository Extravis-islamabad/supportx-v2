import { createContext, useContext, type ReactNode } from 'react';

/**
 * Where knowledge plugs into the incident's editors (D-121; lane A's slot). The incident page
 * provides it; the reply, note and resolution editors only pass it to their toolbar. `insert`
 * puts HTML at the editor's own caret; `audience` says who reads what is written: everyone on the
 * record (a reply, a public note, the resolution) or staff only (a private note).
 */
export type KnowledgeSlot = (
  insert: (html: string) => void,
  audience: 'public' | 'private',
) => ReactNode;

export const KnowledgeSlotContext = createContext<KnowledgeSlot | null>(null);

/** The editor's `extraTools` for this audience, or undefined when no slot is provided. */
export function useKnowledgeTools(
  audience: 'public' | 'private',
): ((insert: (html: string) => void) => ReactNode) | undefined {
  const slot = useContext(KnowledgeSlotContext);
  return slot === null ? undefined : (insert) => slot(insert, audience);
}
