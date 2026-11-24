import { describe, expect, it } from 'vitest';

import { shrinkProblem } from './pending-shrinks.js';

// The exemption list only shrinks, against the target branch, through to its deletion (§8.3).
describe('shrinkProblem', () => {
  const a = 'apps/a.tsx';
  const b = 'apps/b.tsx';

  it('the same list, or a shorter one, passes', () => {
    expect(shrinkProblem({ base: [a, b], baseHasRule: true, current: [a, b] })).toBeNull();
    expect(shrinkProblem({ base: [a, b], baseHasRule: true, current: [a] })).toBeNull();
  });

  it('a file joining the list fails and is named', () => {
    const problem = shrinkProblem({ base: [a], baseHasRule: true, current: [a, b] });
    expect(problem).toContain(b);
    expect(problem).not.toContain(a);
  });

  it('a target branch from before the rule passes (the list starts here)', () => {
    expect(shrinkProblem({ base: null, baseHasRule: false, current: [a, b] })).toBeNull();
  });

  it('deleting the list passes, against a list or after it is gone', () => {
    expect(shrinkProblem({ base: [a], baseHasRule: true, current: null })).toBeNull();
    expect(shrinkProblem({ base: null, baseHasRule: true, current: null })).toBeNull();
  });

  it('once the list is finished and deleted, re-adding it fails', () => {
    const problem = shrinkProblem({ base: null, baseHasRule: true, current: [a] });
    expect(problem).toContain('finished and deleted');
    expect(problem).toContain(a);
    // Even re-adding it empty.
    expect(shrinkProblem({ base: null, baseHasRule: true, current: [] })).not.toBeNull();
  });
});
