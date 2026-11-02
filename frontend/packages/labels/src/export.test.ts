// @vitest-environment node
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { ar } from './resources/ar';
import { en } from './resources/en';
import { ur } from './resources/ur';

// The backend renders exports, report emails and notifications from this dictionary (D-100 D7,
// ADR-034). It is generated, never committed (D-127): `make generated-backend` runs this script.
const SCRIPT = fileURLToPath(new URL('../scripts/export-json.js', import.meta.url));

describe('server-side label copy', () => {
  it('the export carries every label of every language, sorted by key', () => {
    const target = join(mkdtempSync(join(tmpdir(), 'labels-')), 'resources.json');
    execFileSync(process.execPath, [SCRIPT, target]);
    const exported = JSON.parse(readFileSync(target, 'utf8')) as Record<string, object>;
    expect(exported).toEqual({ en, ar, ur });
    const keys = Object.keys(exported.en ?? {});
    expect(keys).toEqual([...keys].sort());
  });
});
