import { describe, expect, it } from 'vitest';

import { mergeGraphs } from './useMapGraph';
import { positionsIn, positionsOut, textOrNull } from './positions';

const CI = 'a0000000-0000-7000-8000-000000000003';
const OTHER = 'a0000000-0000-7000-8000-000000000004';

describe('CMDB map state', () => {
  it('a business view saves CI positions only, never a placeholder key', () => {
    const out = positionsOut(
      new Map([
        [CI, { x: 10.4, y: -3.6 }],
        [`${CI}~r1`, { x: 1, y: 1 }],
        ['r2', { x: 1, y: 1 }],
      ]),
    );
    expect(out).toEqual({ [CI]: { x: 10, y: -4 } });
    expect(positionsIn(out).get(CI)).toEqual({ x: 10, y: -4 });
    expect(textOrNull('  ')).toBeNull();
    expect(textOrNull(' a ')).toBe('a');
  });

  it("two answers' placeholders stay apart, and a shown CI appears once", () => {
    const answer = (from: string) => ({
      from,
      graph: {
        nodes: [
          { key: from, restricted: false, id: from, name: from },
          { key: 'r1', restricted: true },
        ],
        edges: [{ id: null, type_id: 't', from_key: from, to_key: 'r1', version: null }],
        truncated: from === OTHER,
        node_max: 500,
        counts_available: false,
      },
    });
    const merged = mergeGraphs([answer(CI), answer(OTHER)]);
    expect(merged.nodes.map((n) => n.key).sort()).toEqual(
      [CI, `${CI}~r1`, OTHER, `${OTHER}~r1`].sort(),
    );
    expect(merged.edges).toHaveLength(2);
    expect(merged.truncated).toBe(true);
  });
});
