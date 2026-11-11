import { describe, expect, it } from 'vitest';

import { canRedo, canUndo, record, redo, startHistory, undo } from './history';

describe('designer history', () => {
  it('REQ-WF-008 AC2: undoes at least 50 edits and redoes them', () => {
    let h = startHistory(0);
    for (let i = 1; i <= 60; i += 1) h = record(h, i);
    for (let i = 0; i < 60; i += 1) h = undo(h);
    expect(h.present).toBe(0);
    expect(canUndo(h)).toBe(false);
    for (let i = 0; i < 60; i += 1) h = redo(h);
    expect(h.present).toBe(60);
    expect(canRedo(h)).toBe(false);
  });

  it('keeps at most the limit, dropping the oldest', () => {
    let h = startHistory(0);
    for (let i = 1; i <= 10; i += 1) h = record(h, i, 5);
    expect(h.past).toEqual([5, 6, 7, 8, 9]);
  });

  it('a new edit after an undo drops what was undone', () => {
    let h = record(record(startHistory('a'), 'b'), 'c');
    h = undo(h);
    h = record(h, 'd');
    expect([h.past, h.present, h.future]).toEqual([['a', 'b'], 'd', []]);
  });

  it('the same state is not a step', () => {
    const h = startHistory({ n: 1 });
    expect(record(h, h.present)).toBe(h);
  });
});
