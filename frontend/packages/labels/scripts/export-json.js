/**
 * Writes the label dictionary as JSON for the backend (D-100 D7, ADR-034): exports, report
 * emails and notifications render the same labels as the UI, never a copy of their own.
 *
 *   node packages/labels/scripts/export-json.js <output.json>
 *
 * Plain JavaScript; Node's built-in type stripping loads the TypeScript resources it imports.
 * `src/export.test.ts` fails when the committed JSON is out of date.
 */
import { writeFileSync } from 'node:fs';

import { ar } from '../src/resources/ar.ts';
import { en } from '../src/resources/en.ts';
import { ur } from '../src/resources/ur.ts';

/** @returns {Record<string, Record<string, string>>} */
export function dictionary() {
  /** @param {Record<string, string | undefined>} resource */
  const sorted = (resource) =>
    Object.fromEntries(
      Object.entries(resource)
        .filter((entry) => entry[1] !== undefined)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)),
    );
  return { en: sorted(en), ar: sorted(ar), ur: sorted(ur) };
}

const target = process.argv[2];
if (target) {
  writeFileSync(target, `${JSON.stringify(dictionary(), null, 1)}\n`, 'utf8');
}
