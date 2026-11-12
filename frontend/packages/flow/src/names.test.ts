import { describe, expect, it } from 'vitest';

import { stepNames } from './names';

describe('stepNames (QA 2026-11-11 F-07)', () => {
  it('names a step by its type, numbered only when the type repeats', () => {
    const names = stepNames([
      { id: 'start', type: 'start' },
      { id: 'note', type: 'note' },
      { id: 'reply', type: 'wait' },
      { id: 'note_2', type: 'note' },
      { id: 'end', type: 'end' },
    ]);
    expect(names.get('start')).toEqual({ type: 'start' });
    expect(names.get('note')).toEqual({ type: 'note', n: 1 });
    expect(names.get('note_2')).toEqual({ type: 'note', n: 2 });
    expect(names.get('reply')).toEqual({ type: 'wait' });
  });
});
