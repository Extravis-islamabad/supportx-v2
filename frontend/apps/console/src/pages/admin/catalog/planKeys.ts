import type { CatalogItem } from '@supportx/api-client';

type Task = CatalogItem['plan'][number];

/** A key no other step has, for a step that needs one (waits_for names steps by key). */
export function freshKey(tasks: Task[], index: number): string {
  const taken = new Set(tasks.map((t) => t.key).filter(Boolean));
  let n = index + 1;
  while (taken.has(`step_${String(n)}`)) n += 1;
  return `step_${String(n)}`;
}
