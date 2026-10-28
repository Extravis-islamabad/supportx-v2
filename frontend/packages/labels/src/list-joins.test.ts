// @vitest-environment node
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

/*
 * Product owner rule (lane C, #103): a visible list is never joined by hand with ", " or the old
 * `list.separator` label. In Arabic and Urdu that gives the wrong conjunction ("A، B" instead of
 * "A وB") and lets Latin items swap places. Use `useListFormat()` / `formatList()` for lists and
 * `useJoinParts()` for parts of one item. This test scans the app and UI source so a hand join
 * cannot come back unnoticed.
 */

const FRONTEND = fileURLToPath(new URL('../../../', import.meta.url));
const SCANNED = ['apps/console/src', 'apps/portal/src', 'packages/ui/src'];

const HAND_JOIN = [
  /\.join\(\s*', '\s*\)/,
  /\.join\(\s*", "\s*\)/,
  /join\(\s*t\(\s*['"]list\.separator['"]\s*\)\s*\)/,
];

/**
 * Joins that build something no one reads (IDs, CSS, test IDs, query strings). Each entry: the
 * file (relative to `frontend/`), the exact trimmed source line, and why it is not visible text.
 */
const ALLOWED: { file: string; line: string; reason: string }[] = [];

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === 'node_modules' ? [] : sources(path);
    const code = /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name);
    return code && !entry.name.endsWith('.d.ts') ? [path] : [];
  });
}

function handJoins(): { file: string; at: number; line: string }[] {
  return SCANNED.flatMap((root) => sources(join(FRONTEND, root))).flatMap((path) => {
    const file = relative(FRONTEND, path);
    return readFileSync(path, 'utf8')
      .split('\n')
      .flatMap((text, index) =>
        HAND_JOIN.some((pattern) => pattern.test(text))
          ? [{ file, at: index + 1, line: text.trim() }]
          : [],
      );
  });
}

describe('visible lists use the language list format, never a hand join', () => {
  const found = handJoins();

  it('has no hand-joined lists outside the allow-list', () => {
    const offending = found
      .filter((hit) => !ALLOWED.some((a) => a.file === hit.file && a.line === hit.line))
      .map((hit) => `${hit.file}:${String(hit.at)}  ${hit.line}`);
    expect(offending, 'use useListFormat()/formatList() or useJoinParts() instead').toEqual([]);
  });

  it('has no stale allow-list entries', () => {
    const stale = ALLOWED.filter(
      (a) => !found.some((hit) => hit.file === a.file && hit.line === a.line),
    ).map((a) => `${a.file}  ${a.line}`);
    expect(stale).toEqual([]);
  });

  it('really scans the source (a wrong path would pass vacuously)', () => {
    for (const root of SCANNED) {
      expect(sources(join(FRONTEND, root)).length, root).toBeGreaterThan(0);
    }
  });

  it('catches every hand-join spelling it guards against', () => {
    const samples = ["names.join(', ')", 'names.join(", ")', "names.join(t('list.separator'))"];
    for (const sample of samples) {
      expect(HAND_JOIN.some((pattern) => pattern.test(sample))).toBe(true);
    }
    expect(HAND_JOIN.some((pattern) => pattern.test("parts.join(' ')"))).toBe(false);
  });
});
