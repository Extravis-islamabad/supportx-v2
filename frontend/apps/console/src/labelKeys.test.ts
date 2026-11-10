// Every literal label key the console and portal ask for exists (QA10-P1-05/06: three column
// headers named keys that never existed and showed English in Arabic, rule 5d). A plural key
// counts when its `_one` / `_other` forms exist.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { en } from '@supportx/labels';
import { describe, expect, it } from 'vitest';

const ROOTS = [join(__dirname, '.'), join(__dirname, '../../portal/src')];
const KEY = /\bt\(\s*'([a-z0-9_.-]+)'/g;

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(name) && !name.includes('.test.') ? [path] : [];
  });
}

describe('label keys', () => {
  it('every t("…") key in the console and portal has an English label', () => {
    const known = new Set(Object.keys(en));
    const missing = ROOTS.flatMap(sources).flatMap((file) =>
      [...readFileSync(file, 'utf8').matchAll(KEY)]
        .map((m) => m[1] ?? '')
        .filter(
          (key) =>
            !key.endsWith('.') &&
            !known.has(key) &&
            !known.has(`${key}_one`) &&
            !known.has(`${key}_other`),
        )
        .map((key) => `${key} (${file.split('/src/')[1] ?? file})`),
    );
    expect(missing).toEqual([]);
  });
});
