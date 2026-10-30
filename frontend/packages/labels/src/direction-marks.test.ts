import { describe, expect, it } from 'vitest';

import { ar } from './resources/ar';
import { en } from './resources/en';
import { ur } from './resources/ur';

// The isolation rule (packages/labels README): direction comes from isolating filled values,
// never from marks typed into a label. A Latin fragment that would reorder in a right-to-left
// sentence ("UTF-8", ".xlsx") is a placeholder instead, so it is isolated like any value.
const MARKS = /[‎‏‪-‮⁦-⁩]/u;

describe('labels carry no hard-coded direction marks', () => {
  for (const [language, resources] of Object.entries({ en, ar, ur })) {
    it(`${language}: no LRM, RLM, embeddings, overrides or isolates`, () => {
      const marked = Object.entries(resources)
        .filter(([, text]) => text !== undefined && MARKS.test(text))
        .map(([key]) => key);
      expect(marked).toEqual([]);
    });
  }
});
