import { describe, expect, it } from 'vitest';

import { sortSource } from './sort-labels.js';

const file = (body) => `// header\nexport const en = {\n${body}} as const;\n`;

describe('sortSource', () => {
  it('sorts entries by key, keeping continuation lines and comments with their entry', () => {
    const source = file(
      [
        "  'b.two': 'Two',",
        '  // about a.long',
        "  'a.long':",
        "    'A long value',",
        "  'a.short': 'Short',",
        '',
      ].join('\n'),
    );
    expect(sortSource(source)).toBe(
      file(
        [
          '  // about a.long',
          "  'a.long':",
          "    'A long value',",
          "  'a.short': 'Short',",
          "  'b.two': 'Two',",
          '',
        ].join('\n'),
      ),
    );
  });

  it('leaves a sorted file unchanged and refuses a key given twice', () => {
    const sorted = file("  'a': 'A',\n  'b': 'B',\n");
    expect(sortSource(sorted)).toBe(sorted);
    expect(() => sortSource(file("  'a': 'A',\n  'a': 'B',\n"))).toThrow(/twice/);
  });
});
