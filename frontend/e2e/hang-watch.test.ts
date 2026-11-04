import assert from 'node:assert/strict';
import { test } from 'node:test';

import { frameLine, hotFrames, isStuck, Ring, STUCK_AFTER_MS } from './hang-watch.ts';

void test('a frame reads like a stack trace line, counted from 1, without origin or query', () => {
  assert.equal(
    frameLine({
      functionName: 'useLayout',
      url: 'http://localhost:5173/src/shell/TopNav.tsx?t=1730000000',
      location: { lineNumber: 41, columnNumber: 8 },
    }),
    'useLayout (/src/shell/TopNav.tsx:42:9)',
  );
  assert.equal(
    frameLine({ functionName: '', url: '', location: { lineNumber: 0, columnNumber: 0 } }),
    '(anonymous) (<inline>:1:1)',
  );
});

void test('the hot frames are the ones in the most samples, each counted once per sample', () => {
  const samples = [
    ['measure (a.ts:1:1)', 'loop (b.ts:2:1)', 'loop (b.ts:2:1)'],
    ['render (c.ts:3:1)', 'loop (b.ts:2:1)'],
    ['measure (a.ts:1:1)', 'loop (b.ts:2:1)'],
  ];
  assert.deepEqual(hotFrames(samples, 2), [
    { frame: 'loop (b.ts:2:1)', samples: 3 },
    { frame: 'measure (a.ts:1:1)', samples: 2 },
  ]);
});

void test('the ring keeps only the newest entries', () => {
  const ring = new Ring<number>(3);
  for (const n of [1, 2, 3, 4, 5]) ring.push(n);
  assert.deepEqual(ring.all(), [3, 4, 5]);
});

void test('a page is stuck only once it has not answered for the whole limit', () => {
  assert.equal(isStuck(1_000, 1_000 + STUCK_AFTER_MS - 1), false);
  assert.equal(isStuck(1_000, 1_000 + STUCK_AFTER_MS), true);
});
