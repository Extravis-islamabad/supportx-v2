import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { evaluateRules, type FormRule } from './evaluate';

// REQ-INC-037 AC3: the same vectors as the server's test_form_rules_domain.py, never a copy.
interface Vectors {
  base: Record<string, [boolean, boolean]>;
  cases: {
    name: string;
    rules: FormRule[];
    values: Record<string, unknown>;
    expect: {
      fields: Record<string, unknown>;
      set_values: Record<string, unknown>;
      matched: string[];
    };
  }[];
}

const vectors = JSON.parse(
  // Tests run from the package folder; jsdom gives import.meta.url no file path.
  readFileSync(
    resolve(process.cwd(), '../../../docs/architecture/form-rule-vectors.json'),
    'utf-8',
  ),
) as Vectors;

describe('form rules: the shared vectors', () => {
  it.each(vectors.cases.map((c) => [c.name, c] as const))('%s', (_name, item) => {
    const state = evaluateRules(item.rules, vectors.base, item.values);
    for (const [name, wanted] of Object.entries(item.expect.fields)) {
      expect(state.fields[name], name).toEqual(wanted);
    }
    expect(state.set_values).toEqual(item.expect.set_values);
    expect(state.matched).toEqual(item.expect.matched);
  });
});
