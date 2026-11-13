import type { FlowDefinition, FlowPosition } from './definition';

// Automatic layout (REQ-WF-008), written here rather than taken from a library (the
// coordinator, 2026-11-11: no dagre, no elkjs). A small layered layout, top to bottom:
//   1. links that go back to a node still being walked (loops) are set aside;
//   2. each node's row is its longest path from a start (a node never sits above its source);
//   3. within a row, nodes follow the average place of their sources (two sweeps);
//   4. rows are centred on x = 0, so the diagram mirrors cleanly in RTL.
// It is deterministic: the same definition always lays out the same way.

export const COLUMN = 320; // a node is up to ~300 px wide (three outputs side by side)
export const ROW = 140;

export function layout(definition: FlowDefinition): Map<string, FlowPosition> {
  const ids = definition.nodes.map((n) => n.id);
  const known = new Set(ids);
  const out = new Map<string, string[]>(ids.map((id) => [id, []]));
  for (const link of definition.links) {
    if (known.has(link.from) && known.has(link.to)) out.get(link.from)?.push(link.to);
  }
  const forward = forwardLinks(definition, ids, out);
  const rows = longestPath(ids, forward);
  const order = orderRows(ids, rows, forward);
  const positions = new Map<string, FlowPosition>();
  for (const [row, members] of order) {
    members.forEach((id, i) => {
      positions.set(id, { x: Math.round((i - (members.length - 1) / 2) * COLUMN), y: row * ROW });
    });
  }
  return positions;
}

/** The definition with every node placed by `layout`. */
export function withLayout(definition: FlowDefinition): FlowDefinition {
  const placed = layout(definition);
  return {
    ...definition,
    nodes: definition.nodes.map((n) => ({ ...n, position: placed.get(n.id) ?? n.position })),
  };
}

/** The links that are not loops back, by a depth-first walk from the starts, then the rest. */
function forwardLinks(
  definition: FlowDefinition,
  ids: string[],
  out: Map<string, string[]>,
): Map<string, string[]> {
  const starts = definition.nodes.filter((n) => n.type === 'start').map((n) => n.id);
  const state = new Map<string, 'open' | 'done'>();
  const forward = new Map<string, string[]>(ids.map((id) => [id, []]));
  const walk = (root: string) => {
    // An explicit stack: a long workflow never runs out of call stack.
    const stack: [string, number][] = [[root, 0]];
    state.set(root, 'open');
    while (stack.length > 0) {
      const top = stack[stack.length - 1];
      if (top === undefined) break;
      const [id, next] = top;
      const targets = out.get(id) ?? [];
      if (next >= targets.length) {
        state.set(id, 'done');
        stack.pop();
        continue;
      }
      top[1] = next + 1;
      const target = targets[next];
      if (target === undefined) continue;
      const seen = state.get(target);
      if (seen === 'open') continue; // a loop back: drawn, but not used to place rows
      forward.get(id)?.push(target);
      if (seen === undefined) {
        state.set(target, 'open');
        stack.push([target, 0]);
      }
    }
  };
  for (const id of [...starts, ...ids]) if (!state.has(id)) walk(id);
  return forward;
}

function longestPath(ids: string[], forward: Map<string, string[]>): Map<string, number> {
  const incoming = new Map<string, number>(ids.map((id) => [id, 0]));
  for (const targets of forward.values()) {
    for (const t of targets) incoming.set(t, (incoming.get(t) ?? 0) + 1);
  }
  const rows = new Map<string, number>(ids.map((id) => [id, 0]));
  const queue = ids.filter((id) => incoming.get(id) === 0);
  // Nodes join the queue as their last source is placed; a for-of sees what is pushed.
  for (const id of queue) {
    for (const t of forward.get(id) ?? []) {
      rows.set(t, Math.max(rows.get(t) ?? 0, (rows.get(id) ?? 0) + 1));
      const left = (incoming.get(t) ?? 1) - 1;
      incoming.set(t, left);
      if (left === 0) queue.push(t);
    }
  }
  return rows;
}

function orderRows(
  ids: string[],
  rows: Map<string, number>,
  forward: Map<string, string[]>,
): Map<number, string[]> {
  const byRow = new Map<number, string[]>();
  for (const id of ids) {
    const row = rows.get(id) ?? 0;
    byRow.set(row, [...(byRow.get(row) ?? []), id]);
  }
  const sources = new Map<string, string[]>(ids.map((id) => [id, []]));
  for (const [from, targets] of forward) {
    for (const t of targets) sources.get(t)?.push(from);
  }
  const sorted = [...byRow.keys()].sort((a, b) => a - b);
  for (let sweep = 0; sweep < 2; sweep += 1) {
    const place = new Map<string, number>();
    for (const row of sorted) {
      const members = byRow.get(row) ?? [];
      const weight = (id: string, fallback: number) => {
        const from = (sources.get(id) ?? []).filter((s) => place.has(s));
        if (from.length === 0) return fallback;
        return from.reduce((sum, s) => sum + (place.get(s) ?? 0), 0) / from.length;
      };
      const ranked = members
        .map((id, i) => ({ id, i, w: weight(id, i) }))
        .sort((a, b) => a.w - b.w || a.i - b.i)
        .map((r) => r.id);
      byRow.set(row, ranked);
      ranked.forEach((id, i) => place.set(id, i - (ranked.length - 1) / 2));
    }
  }
  return new Map(sorted.map((row) => [row, byRow.get(row) ?? []]));
}

/**
 * Where a new node goes near `at` without covering another: one row lower at a time until no
 * node is within a node's width and a row's height (QA 2026-11-12 V-08: steps dropped onto
 * Start and End until "Tidy layout"). Gives up after 50 rows: the canvas is then tidied by hand.
 */
export function freeSpot(
  at: { x: number; y: number },
  taken: readonly { x: number; y: number }[],
): { x: number; y: number } {
  const covers = (spot: { x: number; y: number }) =>
    taken.some((p) => Math.abs(p.x - spot.x) < COLUMN - 20 && Math.abs(p.y - spot.y) < ROW - 20);
  let spot = at;
  for (let rows = 0; rows < 50 && covers(spot); rows += 1) {
    spot = { x: spot.x, y: spot.y + ROW };
  }
  return spot;
}
