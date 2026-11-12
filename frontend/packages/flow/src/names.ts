// How a step is named to people (QA 2026-11-11 F-07; rule 5d): never by its internal id ("note",
// "reply"), always by its type's label, numbered in order of appearance when a type repeats
// ("Add a note 2"). Pure: the screens add the label.

export interface StepName {
  type: string;
  /** 1, 2, … when the definition has more than one step of this type; undefined otherwise. */
  n?: number;
}

/** Each step's type and, when its type repeats, its number in the order the steps are listed. */
export function stepNames(nodes: readonly { id: string; type: string }[]): Map<string, StepName> {
  const total = new Map<string, number>();
  for (const node of nodes) total.set(node.type, (total.get(node.type) ?? 0) + 1);
  const seen = new Map<string, number>();
  const names = new Map<string, StepName>();
  for (const node of nodes) {
    const n = (seen.get(node.type) ?? 0) + 1;
    seen.set(node.type, n);
    names.set(
      node.id,
      (total.get(node.type) ?? 0) > 1 ? { type: node.type, n } : { type: node.type },
    );
  }
  return names;
}
