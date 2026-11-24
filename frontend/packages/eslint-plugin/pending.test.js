import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { Linter } from 'eslint';
import tseslint from 'typescript-eslint';
import { describe, expect, it } from 'vitest';

import plugin from './index.js';

// The `channel-covers` exemption list only shrinks (architecture.md §8.3): every file on it must
// exist and still have a channel hook without `covers`. A converted or removed file left on the
// list fails here, so the list can't quietly keep exempting a file that new code then grows into.
const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '../..');
const { files } = JSON.parse(readFileSync(resolve(here, 'channel-covers-pending.json'), 'utf8'));

const linter = new Linter({ configType: 'flat', cwd: root });
const config = [
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { supportx: plugin },
    rules: { 'supportx/channel-covers': 'error' },
  },
];

describe('channel-covers-pending.json', () => {
  it('is sorted and has no duplicates', () => {
    expect(files).toEqual([...new Set(files)].sort());
  });

  it.each(files)('%s exists and still needs converting', (file) => {
    const path = resolve(root, file);
    expect(existsSync(path), `${file} no longer exists: remove it from the list`).toBe(true);
    const found = linter
      .verify(readFileSync(path, 'utf8'), config, path)
      .filter((m) => m.ruleId === 'supportx/channel-covers');
    expect(found.length, `${file} is converted: remove it from the list`).toBeGreaterThan(0);
  });
});
