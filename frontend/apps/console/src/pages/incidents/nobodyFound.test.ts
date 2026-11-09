import { describe, expect, it } from 'vitest';

import { nobodyFound } from './nobodyFound';

describe('nobodyFound (QA9-F-04)', () => {
  it('asks for a second letter rather than saying nobody was found', () => {
    expect(nobodyFound('a')).toBe('incidents.type_two_letters');
    expect(nobodyFound(' a ')).toBe('incidents.type_two_letters');
    expect(nobodyFound('ab')).toBe('incidents.nobody_found');
    expect(nobodyFound('')).toBe('incidents.nobody_found');
  });
});
