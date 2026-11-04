import assert from 'node:assert/strict';
import { test } from 'node:test';

import { assign, weightsFrom } from './shards.ts';

void test('the slow specs are spread out, and every spec runs exactly once', () => {
  const weights = { 'tests/a.spec.ts': 300, 'tests/b.spec.ts': 290, 'tests/c.spec.ts': 10 };
  const files = [...Object.keys(weights), 'tests/new.spec.ts'];
  const shards = assign(files, weights, 2);
  assert.deepEqual(shards, [
    ['tests/a.spec.ts', 'tests/c.spec.ts'], // 300 + 10
    ['tests/b.spec.ts', 'tests/new.spec.ts'], // 290 + 30 (unmeasured: the default)
  ]);
  assert.deepEqual(shards.flat().sort(), [...files].sort());
});

void test('weights add up each spec file, retries and minutes included', () => {
  const log = [
    '  ✓   1 [chromium] › tests/a.spec.ts:10:1 › first (12.4s)',
    '  ✘   2 [chromium] › tests/b.spec.ts:5:1 › slow (2.0m)',
    '  ✘   3 [chromium] › tests/b.spec.ts:5:1 › slow (retry #1) (1.5m)',
    'unrelated line',
  ].join('\n');
  assert.deepEqual(weightsFrom(log), { 'tests/a.spec.ts': 13, 'tests/b.spec.ts': 210 });
});
