// The CMDB relationship map's layouts (WP-053 S2, REQ-CMDB-008; lane C's conditions 5 to 7).
// Written here, as the workflow layout is (the coordinator, 2026-11-11: no dagre, no elkjs).
// Pure functions: the same nodes and links always lay out the same way (every list is sorted
// before it is walked), and a node already placed is never moved: expanding a node only finds
// free spots for the new ones (AC1). Positions are stored left to right; right to left mirrors
// the x-coordinates (`mirrored`), never the canvas through CSS (condition 7).

export type CiMapLayout = 'radial' | 'hierarchical' | 'tree';
export const CI_MAP_LAYOUTS: readonly CiMapLayout[] = ['radial', 'hierarchical', 'tree'];

export interface MapPoint {
  x: number;
  y: number;
}

export interface MapLink {
  from: string;
  to: string;
}

export interface MapLayoutInput {
  /** The CI the map starts from (centre, or top). */
  base: string;
  /** Every node key on the map. */
  keys: readonly string[];
  links: readonly MapLink[];
  layout: CiMapLayout;
  /** Nodes already on screen (or pinned by a business view): they keep these spots. */
  placed?: ReadonlyMap<string, MapPoint>;
}

export const MAP_NODE_WIDTH = 200;
export const MAP_NODE_HEIGHT = 64;
export const MAP_COLUMN = 240; // a node and the gap beside it
export const MAP_ROW = 140;
export const MAP_RING = 240;

const GAP_X = MAP_COLUMN - 20;
const GAP_Y = MAP_ROW - 40;

/** Breadth first from the base over the links both ways; the parent each node was reached by. */
function walk(input: MapLayoutInput): {
  order: string[];
  depth: Map<string, number>;
  parent: Map<string, string>;
} {
  const keys = [...new Set(input.keys)].sort();
  const known = new Set(keys);
  const next = new Map<string, string[]>(keys.map((k) => [k, []]));
  for (const link of input.links) {
    if (!known.has(link.from) || !known.has(link.to) || link.from === link.to) continue;
    next.get(link.from)?.push(link.to);
    next.get(link.to)?.push(link.from);
  }
  for (const list of next.values()) list.sort();
  const depth = new Map<string, number>();
  const parent = new Map<string, string>();
  const order: string[] = [];
  const visit = (start: string, at: number) => {
    depth.set(start, at);
    const queue = [start];
    // for-of over the queue sees what is pushed while it walks (a breadth-first queue).
    for (const key of queue) {
      order.push(key);
      for (const other of next.get(key) ?? []) {
        if (depth.has(other)) continue;
        depth.set(other, (depth.get(key) ?? 0) + 1);
        parent.set(other, key);
        queue.push(other);
      }
    }
  };
  if (known.has(input.base)) visit(input.base, 0);
  // Nodes no link reaches from the base (a filter cut them off) go one ring or row further out.
  const furthest = Math.max(0, ...depth.values());
  for (const key of keys) if (!depth.has(key)) visit(key, furthest + 1);
  return { order, depth, parent };
}

/** Each depth's members, in walk order (sorted ties), parents before children. */
function byDepth(
  order: readonly string[],
  depth: ReadonlyMap<string, number>,
): Map<number, string[]> {
  const rows = new Map<number, string[]>();
  for (const key of order) {
    const d = depth.get(key) ?? 0;
    rows.set(d, [...(rows.get(d) ?? []), key]);
  }
  return new Map([...rows.entries()].sort(([a], [b]) => a - b));
}

function radial(
  order: readonly string[],
  depth: ReadonlyMap<string, number>,
  parent: ReadonlyMap<string, string>,
): Map<string, MapPoint> {
  const out = new Map<string, MapPoint>();
  const angle = new Map<string, number>();
  for (const [d, members] of byDepth(order, depth)) {
    if (d === 0) {
      for (const key of members) {
        out.set(key, { x: 0, y: 0 });
        angle.set(key, -Math.PI / 2);
      }
      continue;
    }
    // Children sit in their parent's angular order, so links cross as little as they can.
    const ranked = [...members].sort((a, b) => {
      const pa = angle.get(parent.get(a) ?? '') ?? 0;
      const pb = angle.get(parent.get(b) ?? '') ?? 0;
      return pa === pb ? (a < b ? -1 : a > b ? 1 : 0) : pa - pb;
    });
    const radius = Math.max(d * MAP_RING, (ranked.length * MAP_COLUMN) / (2 * Math.PI));
    ranked.forEach((key, i) => {
      const theta = -Math.PI / 2 + (2 * Math.PI * i) / ranked.length;
      angle.set(key, theta);
      out.set(key, {
        x: Math.round(radius * Math.cos(theta)),
        y: Math.round(radius * Math.sin(theta)),
      });
    });
  }
  return out;
}

function hierarchical(
  order: readonly string[],
  depth: ReadonlyMap<string, number>,
  parent: ReadonlyMap<string, string>,
): Map<string, MapPoint> {
  const out = new Map<string, MapPoint>();
  for (const [d, members] of byDepth(order, depth)) {
    // Within a row, nodes follow their parent's place (one sweep), ties by key.
    const ranked = [...members].sort((a, b) => {
      const pa = out.get(parent.get(a) ?? '')?.x ?? 0;
      const pb = out.get(parent.get(b) ?? '')?.x ?? 0;
      return pa === pb ? (a < b ? -1 : a > b ? 1 : 0) : pa - pb;
    });
    ranked.forEach((key, i) => {
      out.set(key, { x: Math.round((i - (ranked.length - 1) / 2) * MAP_COLUMN), y: d * MAP_ROW });
    });
  }
  return out;
}

function tree(
  order: readonly string[],
  depth: ReadonlyMap<string, number>,
  parent: ReadonlyMap<string, string>,
): Map<string, MapPoint> {
  const children = new Map<string, string[]>();
  const roots: string[] = [];
  for (const key of order) {
    const p = parent.get(key);
    if (p === undefined) roots.push(key);
    else children.set(p, [...(children.get(p) ?? []), key]);
  }
  const out = new Map<string, MapPoint>();
  let slot = 0;
  // A tidy tree, iteratively (a deep chain of 1,000 must not overflow the stack): leaves take
  // the next column, a parent sits over the middle of its children.
  for (const root of roots) {
    const stack: { key: string; done: boolean }[] = [{ key: root, done: false }];
    while (stack.length > 0) {
      const top = stack.pop();
      if (top === undefined) break;
      const kids = children.get(top.key) ?? [];
      const y = (depth.get(top.key) ?? 0) * MAP_ROW;
      if (kids.length === 0) {
        out.set(top.key, { x: slot * MAP_COLUMN, y });
        slot += 1;
      } else if (top.done) {
        const first = out.get(kids[0] ?? '')?.x ?? 0;
        const last = out.get(kids.at(-1) ?? '')?.x ?? 0;
        out.set(top.key, { x: Math.round((first + last) / 2), y });
      } else {
        stack.push({ key: top.key, done: true });
        for (const kid of [...kids].reverse()) stack.push({ key: kid, done: false });
      }
    }
  }
  // Centred on the base's column, so the tree mirrors cleanly in RTL.
  const shift = out.get(roots[0] ?? '')?.x ?? 0;
  for (const [key, p] of out) out.set(key, { x: p.x - shift, y: p.y });
  return out;
}

/** Occupied spots in a grid of cells, so a free-spot search stays fast with 1,000 nodes. */
class Taken {
  private readonly cells = new Map<string, MapPoint[]>();

  private static cell(x: number, y: number): string {
    return `${String(Math.floor(x / MAP_COLUMN))}:${String(Math.floor(y / MAP_ROW))}`;
  }

  add(p: MapPoint): void {
    const key = Taken.cell(p.x, p.y);
    this.cells.set(key, [...(this.cells.get(key) ?? []), p]);
  }

  covers(p: MapPoint): boolean {
    const cx = Math.floor(p.x / MAP_COLUMN);
    const cy = Math.floor(p.y / MAP_ROW);
    for (let dx = -1; dx <= 1; dx += 1) {
      for (let dy = -1; dy <= 1; dy += 1) {
        for (const q of this.cells.get(`${String(cx + dx)}:${String(cy + dy)}`) ?? []) {
          if (Math.abs(q.x - p.x) < GAP_X && Math.abs(q.y - p.y) < GAP_Y) return true;
        }
      }
    }
    return false;
  }
}

/** Spots to try for a new node next to its parent, nearest first. */
function* candidates(layout: CiMapLayout, at: MapPoint, base: MapPoint): Generator<MapPoint> {
  if (layout === 'radial') {
    const away =
      at.x === base.x && at.y === base.y ? -Math.PI / 2 : Math.atan2(at.y - base.y, at.x - base.x);
    for (let ring = 1; ring <= 12; ring += 1) {
      const r = ring * MAP_RING * (ring === 1 ? 1 : 0.75);
      const steps = 6 + ring * 4;
      for (let i = 0; i < steps; i += 1) {
        // 0, +1, -1, +2, -2 … steps around the outward direction.
        const k = i % 2 === 0 ? i / 2 : -(i + 1) / 2;
        const theta = away + (k * 2 * Math.PI) / steps;
        yield {
          x: Math.round(at.x + r * Math.cos(theta)),
          y: Math.round(at.y + r * Math.sin(theta)),
        };
      }
    }
    return;
  }
  for (let row = 1; row <= 30; row += 1) {
    for (let i = 0; i < 41; i += 1) {
      const k = i % 2 === 0 ? i / 2 : -(i + 1) / 2;
      yield { x: at.x + k * MAP_COLUMN, y: at.y + row * MAP_ROW };
    }
  }
}

/**
 * Where every node goes. Without `placed`, the whole map is laid out. With it, placed nodes keep
 * their spots exactly and only the others are found room, next to the node they were reached
 * from (AC1: expanding never moves what is on screen).
 */
export function layoutMap(input: MapLayoutInput): Map<string, MapPoint> {
  const { order, depth, parent } = walk(input);
  const placed = input.placed;
  if (placed === undefined || ![...placed.keys()].some((k) => depth.has(k))) {
    if (input.layout === 'radial') return radial(order, depth, parent);
    if (input.layout === 'tree') return tree(order, depth, parent);
    return hierarchical(order, depth, parent);
  }
  const out = new Map<string, MapPoint>();
  const taken = new Taken();
  for (const key of order) {
    const at = placed.get(key);
    if (at === undefined) continue;
    out.set(key, { x: at.x, y: at.y });
    taken.add(at);
  }
  const base = out.get(input.base) ?? { x: 0, y: 0 };
  for (const key of order) {
    if (out.has(key)) continue;
    const from = out.get(parent.get(key) ?? '') ?? base;
    let spot: MapPoint | undefined;
    for (const candidate of candidates(input.layout, from, base)) {
      if (!taken.covers(candidate)) {
        spot = candidate;
        break;
      }
    }
    // Every nearby spot taken (a very crowded map): the next free row below everything.
    if (spot === undefined) {
      const bottom = Math.max(...[...out.values()].map((p) => p.y));
      spot = { x: from.x, y: bottom + MAP_ROW };
      while (taken.covers(spot)) spot = { x: spot.x + MAP_COLUMN, y: spot.y };
    }
    out.set(key, spot);
    taken.add(spot);
  }
  return out;
}

/** Positions as drawn: in right to left the x-coordinates mirror (condition 7). */
export function mirrored(
  positions: ReadonlyMap<string, MapPoint>,
  rtl: boolean,
): Map<string, MapPoint> {
  return new Map(
    [...positions].map(([key, p]) => [key, { x: rtl && p.x !== 0 ? -p.x : p.x, y: p.y }]),
  );
}

export type MapArrow = 'ArrowUp' | 'ArrowDown' | 'ArrowLeft' | 'ArrowRight';

export const isMapArrow = (key: string): key is MapArrow =>
  key === 'ArrowUp' || key === 'ArrowDown' || key === 'ArrowLeft' || key === 'ArrowRight';

/**
 * The node an arrow key moves to, from the positions as drawn (so in right to left, where the
 * map is mirrored, ArrowRight still goes to the node on the screen's right; condition 6): the
 * nearest node that way, closeness across the arrow counting double. Ties by key.
 */
export function nextNode(
  from: string,
  shown: ReadonlyMap<string, MapPoint>,
  arrow: MapArrow,
): string | undefined {
  const at = shown.get(from);
  if (at === undefined) return undefined;
  let best: { key: string; score: number } | undefined;
  for (const [key, p] of [...shown].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) {
    if (key === from) continue;
    const dx = p.x - at.x;
    const dy = p.y - at.y;
    const along =
      arrow === 'ArrowRight' ? dx : arrow === 'ArrowLeft' ? -dx : arrow === 'ArrowDown' ? dy : -dy;
    const across = arrow === 'ArrowRight' || arrow === 'ArrowLeft' ? Math.abs(dy) : Math.abs(dx);
    if (along <= 0) continue;
    const score = along + 2 * across;
    if (best === undefined || score < best.score) best = { key, score };
  }
  return best?.key;
}
