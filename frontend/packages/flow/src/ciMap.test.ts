import { describe, expect, it } from 'vitest';

import {
  CI_MAP_LAYOUTS,
  MAP_COLUMN,
  MAP_ROW,
  layoutMap,
  mirrored,
  nextNode,
  type MapLink,
  type MapPoint,
} from './ciMap';
import { CSV_BOM, csvCell, mapCsv, mapSvg, xmlEscape, type MapCsvWords } from './ciExport';

// WP-053 S2, lane C's conditions 5 (pure layouts: deterministic, expand never moves placed nodes,
// 1,000 nodes under a second), 6 and 7 (arrows by what is drawn, RTL mirrors x), 11 and 12.

/** A star of `spokes` around `base`, each spoke with `leaves` of its own. */
function star(spokes: number, leaves: number): { keys: string[]; links: MapLink[] } {
  const keys = ['base'];
  const links: MapLink[] = [];
  for (let s = 0; s < spokes; s += 1) {
    const spoke = `s${String(s).padStart(4, '0')}`;
    keys.push(spoke);
    links.push({ from: 'base', to: spoke });
    for (let l = 0; l < leaves; l += 1) {
      const leaf = `${spoke}-l${String(l).padStart(3, '0')}`;
      keys.push(leaf);
      links.push({ from: leaf, to: spoke });
    }
  }
  return { keys, links };
}

/** How many nodes sit exactly on another one. */
const overlaps = (positions: Map<string, MapPoint>) => {
  const spots = new Set(
    [...positions.values()].map((p) => `${String(Math.round(p.x))}:${String(Math.round(p.y))}`),
  );
  return positions.size - spots.size;
};

describe('CMDB map layouts', () => {
  it.each(CI_MAP_LAYOUTS)('%s is deterministic, whatever order the nodes come in', (layout) => {
    const { keys, links } = star(6, 3);
    const first = layoutMap({ base: 'base', keys, links, layout });
    const shuffled = layoutMap({
      base: 'base',
      keys: [...keys].reverse(),
      links: [...links].reverse(),
      layout,
    });
    expect([...shuffled.entries()].sort()).toEqual([...first.entries()].sort());
    expect(first.size).toBe(keys.length);
    expect(overlaps(first)).toBe(0);
  });

  it.each(CI_MAP_LAYOUTS)('%s: expanding a node never moves a placed one (AC1)', (layout) => {
    const { keys, links } = star(5, 0);
    const before = layoutMap({ base: 'base', keys, links, layout });
    const added = ['n1', 'n2', 'n3', 'n4'];
    const after = layoutMap({
      base: 'base',
      keys: [...keys, ...added],
      links: [...links, ...added.map((to) => ({ from: 's0002', to }))],
      layout,
      placed: before,
    });
    for (const [key, at] of before) expect(after.get(key)).toEqual(at);
    for (const key of added) expect(after.has(key)).toBe(true);
    // The new nodes found room: none sits on another node.
    expect(overlaps(after)).toBe(0);
  });

  it('keeps pinned positions of a business view, and finds room for the rest', () => {
    const { keys, links } = star(3, 0);
    const pinned = new Map<string, MapPoint>([
      ['base', { x: 0, y: 0 }],
      ['s0001', { x: 900, y: -400 }],
    ]);
    const out = layoutMap({ base: 'base', keys, links, layout: 'radial', placed: pinned });
    expect(out.get('s0001')).toEqual({ x: 900, y: -400 });
    expect(out.get('base')).toEqual({ x: 0, y: 0 });
    expect(out.size).toBe(4);
  });

  it.each(CI_MAP_LAYOUTS)('%s lays out 1,000 nodes in under a second', (layout) => {
    const { keys, links } = star(40, 24); // 1 + 40 + 960 = 1,001 nodes
    expect(keys.length).toBeGreaterThanOrEqual(1000);
    const started = performance.now();
    const out = layoutMap({ base: 'base', keys, links, layout });
    expect(performance.now() - started).toBeLessThan(1000);
    expect(out.size).toBe(keys.length);
  });

  it('expands 1,000 new nodes around placed ones in under a second', () => {
    const { keys, links } = star(40, 0);
    const before = layoutMap({ base: 'base', keys, links, layout: 'hierarchical' });
    const extra = star(40, 24);
    const started = performance.now();
    const out = layoutMap({ ...extra, base: 'base', layout: 'hierarchical', placed: before });
    expect(performance.now() - started).toBeLessThan(1000);
    for (const [key, at] of before) expect(out.get(key)).toEqual(at);
  });

  it('hierarchical puts the base on top and each ring a row lower', () => {
    const { keys, links } = star(2, 1);
    const out = layoutMap({ base: 'base', keys, links, layout: 'hierarchical' });
    expect(out.get('base')).toEqual({ x: 0, y: 0 });
    expect(out.get('s0000')?.y).toBe(MAP_ROW);
    expect(out.get('s0000-l000')?.y).toBe(2 * MAP_ROW);
  });

  it('a node no link reaches still gets a place', () => {
    const out = layoutMap({ base: 'base', keys: ['base', 'alone'], links: [], layout: 'tree' });
    expect(out.size).toBe(2);
    expect(out.get('alone')).not.toEqual(out.get('base'));
  });
});

describe('CMDB map: right to left and the arrow keys', () => {
  const row = new Map<string, MapPoint>([
    ['base', { x: 0, y: 0 }],
    ['east', { x: MAP_COLUMN, y: 0 }],
    ['west', { x: -MAP_COLUMN, y: 0 }],
    ['below', { x: 0, y: MAP_ROW }],
  ]);

  it('mirrors the x-coordinates, never y (condition 7)', () => {
    const shown = mirrored(row, true);
    expect(shown.get('east')).toEqual({ x: -MAP_COLUMN, y: 0 });
    expect(shown.get('below')).toEqual({ x: 0, y: MAP_ROW });
    expect(mirrored(row, false)).toEqual(row);
  });

  it('arrows follow what is drawn, so they mirror with the map (condition 6)', () => {
    expect(nextNode('base', row, 'ArrowRight')).toBe('east');
    expect(nextNode('base', row, 'ArrowLeft')).toBe('west');
    expect(nextNode('base', row, 'ArrowDown')).toBe('below');
    expect(nextNode('base', row, 'ArrowUp')).toBeUndefined();
    const rtl = mirrored(row, true);
    // In Arabic "east" is drawn on the left: ArrowLeft reaches it.
    expect(nextNode('base', rtl, 'ArrowLeft')).toBe('east');
    expect(nextNode('base', rtl, 'ArrowRight')).toBe('west');
  });
});

describe('CMDB map exports', () => {
  const words: MapCsvWords = {
    header: [
      'From ID',
      'From',
      'From type',
      'From state',
      'Relationship',
      'To ID',
      'To',
      'To type',
      'To state',
    ],
    restricted: 'restricted',
  };

  it('defuses spreadsheet formulas and quotes what needs it (condition 11)', () => {
    expect(csvCell('=HYPERLINK("x")')).toBe(`"'=HYPERLINK(""x"")"`);
    expect(csvCell('+1')).toBe("'+1");
    expect(csvCell('-2')).toBe("'-2");
    expect(csvCell('@SUM(A1)')).toBe("'@SUM(A1)");
    expect(csvCell('\tcmd')).toBe("'\tcmd");
    expect(csvCell('\rcmd')).toBe(`"'\rcmd"`);
    expect(csvCell('a,b')).toBe('"a,b"');
    expect(csvCell('خادم البريد')).toBe('خادم البريد');
  });

  it('starts with a BOM and shows a restricted end with no ID', () => {
    const csv = mapCsv(
      [
        {
          from: {
            restricted: false,
            displayId: 'CI-1',
            name: '=cmd',
            type: 'Server',
            state: 'In use',
          },
          relationship: 'runs on',
          to: { restricted: true },
        },
      ],
      words,
    );
    expect(csv.startsWith(CSV_BOM)).toBe(true);
    const lines = csv.slice(1).trimEnd().split('\r\n');
    expect(lines).toHaveLength(2);
    expect(lines[1]).toBe("CI-1,'=cmd,Server,In use,runs on,restricted,restricted,,");
  });

  it('writes an inert SVG, even for a CI named <script>"&\' (condition 12)', () => {
    const name = `<script>"&'`;
    const svg = mapSvg({
      title: name,
      background: 'url(javascript:alert(1))',
      line: '#999999',
      rtl: false,
      edges: [{ x1: 0, y1: 0, x2: 100, y2: 100, label: name }],
      nodes: [
        {
          x: 0,
          y: 0,
          width: 200,
          height: 64,
          title: name,
          subtitle: `" onload="alert(1)`,
          fill: '#ffffff',
          stroke: '#000000',
          text: '#000000',
        },
      ],
    });
    expect(svg).not.toContain('<script');
    expect(svg).toContain('&lt;script&gt;&quot;&amp;&apos;');
    expect(svg).not.toMatch(/foreignObject/i);
    expect(svg).not.toMatch(/href/i);
    // No event attribute on any element. Only the tags are checked: the escaped subtitle
    // `&quot; onload=&quot;…` stays inert text inside <text>, which is the point of the test.
    const tagsOnly = [...svg.matchAll(/<[^>]*>/g)].map((m) => m[0]).join('\n');
    expect(tagsOnly).not.toMatch(/\son[a-z]+\s*=/i);
    expect(tagsOnly).not.toContain('alert');
    expect(svg).toContain('&quot; onload=&quot;alert(1)</text>');
    expect(svg).not.toMatch(/url\(|@import|@font-face|<style/i);
    // Only the elements the serialiser allows.
    const tags = new Set([...svg.matchAll(/<([a-zA-Z][\w:-]*)/g)].map((m) => m[1]));
    expect(
      [...tags].every((tag) => ['svg', 'title', 'rect', 'line', 'text', 'g'].includes(tag ?? '')),
    ).toBe(true);
    // Control characters XML does not allow are dropped.
    expect(xmlEscape('a\u0001b')).toBe('ab');
  });

  it('anchors text at the end in right to left', () => {
    const svg = mapSvg({
      title: 'خريطة',
      background: '#ffffff',
      line: '#999999',
      rtl: true,
      edges: [],
      nodes: [
        {
          x: 0,
          y: 0,
          width: 200,
          height: 64,
          title: 'خادم',
          subtitle: 'خادم · قيد الاستخدام',
          fill: '#ffffff',
          stroke: '#000000',
          text: '#000000',
          dashed: true,
        },
      ],
    });
    expect(svg).toContain('direction="rtl"');
    expect(svg).toContain('text-anchor="end"');
    expect(svg).toContain('stroke-dasharray');
  });
});
