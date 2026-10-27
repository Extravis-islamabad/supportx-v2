// @vitest-environment node
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { ar } from './resources/ar';
import { en } from './resources/en';
import { ur } from './resources/ur';

// The backend renders exports, report emails and notifications from this JSON copy (D-100 D7,
// ADR-034). Regenerate it with `make labels-json` after changing any label.
const EXPORTED = fileURLToPath(
  new URL('../../../../backend/app/shared/labels/resources.json', import.meta.url),
);

describe('server-side label copy', () => {
  it('matches the label resources exactly', () => {
    const exported = JSON.parse(readFileSync(EXPORTED, 'utf8')) as Record<string, unknown>;
    expect(exported).toEqual({ en, ar, ur });
  });
});
