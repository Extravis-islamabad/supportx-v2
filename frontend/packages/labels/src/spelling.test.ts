import { describe, expect, it } from 'vitest';

import { en } from './resources/en';

// UK spelling is the house style (the coordinator, 2026-11-11): "organisation", "licence", and
// "Cancelled". Only the English TEXT follows it: keys and stable codes (`canceled`,
// `task_canceled`, ...) are stored data and API contracts and never change.
const US_FORMS: [RegExp, string][] = [[/\bcancel(ed|ing)\b/i, 'Cancelled / cancelling']];

describe('English label text', () => {
  it('uses UK spelling (Cancelled, never Canceled)', () => {
    const found = Object.entries(en as Record<string, string>).flatMap(([key, text]) =>
      US_FORMS.filter(([us]) => us.test(text)).map(([, uk]) => `${key}: write ${uk}`),
    );
    expect(found).toEqual([]);
  });
});
