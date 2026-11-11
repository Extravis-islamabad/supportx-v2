import { describe, expect, it } from 'vitest';

import { readDefinition, type FlowDefinition, type FlowNodeDef } from './definition';
import { fromGraph, toGraph } from './graph';
import { COLUMN, ROW, layout, withLayout } from './layout';

const node = (id: string, type: string, x = 0, y = 0): FlowNodeDef => ({
  id,
  type,
  config: type === 'notify' ? { subject: { en: 'Hi' } } : {},
  position: { x, y },
});

// REQ-WF-008 AC1's workflow: start → if → notification → set status → end.
const FLOW: FlowDefinition = {
  format: 1,
  nodes: [
    node('s', 'start', 0, 0),
    node('check', 'if', 0, 140),
    node('tell', 'notify', -130, 280),
    node('status', 'set_status', -130, 420),
    node('e', 'end', 0, 560),
  ],
  links: [
    { from: 's', port: 'next', to: 'check' },
    { from: 'check', port: 'true', to: 'tell' },
    { from: 'check', port: 'false', to: 'e' },
    { from: 'tell', port: 'next', to: 'status' },
    { from: 'status', port: 'next', to: 'e' },
  ],
  variables: [{ name: 'answer', type: 'number' }],
};

const PORTS = (n: FlowNodeDef) =>
  n.type === 'if' ? ['true', 'false'] : n.type === 'end' ? [] : ['next'];

describe('definition ↔ graph', () => {
  it.each([false, true])(
    'REQ-WF-008 AC3: a definition re-opens to the same diagram (rtl %s)',
    (rtl) => {
      const { nodes, edges } = toGraph(FLOW, { ports: PORTS, rtl });
      expect(fromGraph(FLOW, nodes, edges, { rtl })).toEqual(FLOW);
    },
  );

  it('mirrors positions in RTL, keeping them left to right in the definition', () => {
    const { nodes } = toGraph(FLOW, { ports: PORTS, rtl: true });
    expect(nodes.find((n) => n.id === 'tell')?.position).toEqual({ x: 130, y: 280 });
    const moved = nodes.map((n) => (n.id === 'tell' ? { ...n, position: { x: 200, y: 300 } } : n));
    const saved = fromGraph(FLOW, moved, toGraph(FLOW, { ports: PORTS, rtl: true }).edges, {
      rtl: true,
    });
    expect(saved.nodes.find((n) => n.id === 'tell')?.position).toEqual({ x: -200, y: 300 });
  });

  it('gives each link its output as the handle it leaves by', () => {
    const { edges, nodes } = toGraph(FLOW, { ports: PORTS, rtl: false });
    expect(edges.find((e) => e.source === 'check' && e.target === 'tell')?.sourceHandle).toBe(
      'true',
    );
    expect(nodes.find((n) => n.id === 'check')?.data.ports).toEqual(['true', 'false']);
  });

  it('reads an untrusted definition without trusting its shape', () => {
    const read = readDefinition({
      nodes: [{ id: 'a', type: 'start', position: { x: 'far' } }, 'junk', null],
      links: [{ from: 'a', to: 'b' }],
    });
    expect(read).toEqual({
      format: 1,
      nodes: [{ id: 'a', type: 'start', config: {}, position: { x: 0, y: 0 } }],
      links: [{ from: 'a', port: '', to: 'b' }],
      variables: [],
    });
  });
});

describe('automatic layout', () => {
  it('places each node below its source, branches side by side', () => {
    const placed = layout(FLOW);
    const y = (id: string) => placed.get(id)?.y ?? -1;
    expect([y('s'), y('check'), y('tell'), y('status'), y('e')]).toEqual([
      0,
      ROW,
      2 * ROW,
      3 * ROW,
      4 * ROW, // the end waits for its longest path, not the short "false" branch
    ]);
    expect(placed.get('s')?.x).toBe(0); // a row of one is centred
  });

  it('centres a row of two on x = 0, a column apart', () => {
    const split: FlowDefinition = {
      ...FLOW,
      nodes: [node('s', 'start'), node('a', 'note'), node('b', 'note'), node('e', 'end')],
      links: [
        { from: 's', port: 'one', to: 'a' },
        { from: 's', port: 'two', to: 'b' },
        { from: 'a', port: 'next', to: 'e' },
        { from: 'b', port: 'next', to: 'e' },
      ],
    };
    const placed = layout(split);
    expect([placed.get('a')?.x, placed.get('b')?.x]).toEqual([-COLUMN / 2, COLUMN / 2]);
    expect(placed.get('e')).toEqual({ x: 0, y: 2 * ROW });
  });

  it('lays out a loop without hanging, the loop target staying above', () => {
    const loop: FlowDefinition = {
      ...FLOW,
      nodes: [node('s', 'start'), node('w', 'wait'), node('t', 'timer'), node('e', 'end')],
      links: [
        { from: 's', port: 'next', to: 'w' },
        { from: 'w', port: 'next', to: 't' },
        { from: 't', port: 'next', to: 'w' }, // back to the wait
        { from: 'w', port: 'overtaken', to: 'e' },
      ],
    };
    const placed = layout(loop);
    expect((placed.get('w')?.y ?? 0) < (placed.get('t')?.y ?? 0)).toBe(true);
    expect(placed.size).toBe(4);
  });

  it('places nodes nothing links to, and is the same every time', () => {
    const loose: FlowDefinition = { ...FLOW, nodes: [...FLOW.nodes, node('stray', 'note')] };
    const first = layout(loose);
    expect(first.has('stray')).toBe(true);
    expect(layout(loose)).toEqual(first);
    expect(withLayout(loose).nodes.map((n) => n.id)).toEqual(loose.nodes.map((n) => n.id));
  });

  it('handles a long chain', () => {
    const count = 500;
    const chain: FlowDefinition = {
      ...FLOW,
      nodes: Array.from({ length: count }, (_, i) =>
        node(`n${String(i)}`, i === 0 ? 'start' : 'note'),
      ),
      links: Array.from({ length: count - 1 }, (_, i) => ({
        from: `n${String(i)}`,
        port: 'next',
        to: `n${String(i + 1)}`,
      })),
    };
    expect(layout(chain).get(`n${String(count - 1)}`)?.y).toBe((count - 1) * ROW);
  });
});
