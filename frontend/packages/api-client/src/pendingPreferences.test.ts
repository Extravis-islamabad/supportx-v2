import { beforeEach, describe, expect, it } from 'vitest';

import {
  clearPending,
  readPending,
  setPending,
  settlePendingAfterError,
} from './pendingPreferences';

// The flaky qa-fixes BUG-04 e2e test: a language picked just before a reload was lost.
describe('pending preferences', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('keep a choice whose save was cut off; forget it once saved or refused', () => {
    setPending('u1', 'ui_locale', 'ar');
    settlePendingAfterError('u1', 'ui_locale', 'ar', new TypeError('Failed to fetch'));
    expect(readPending('u1')).toEqual({ ui_locale: 'ar' }); // aborted by the reload: kept
    settlePendingAfterError('u1', 'ui_locale', 'ar', { status: 422 });
    expect(readPending('u1')).toEqual({}); // refused by the server: forgotten
    setPending('u1', 'nav_layout', 'side');
    clearPending('u1', 'nav_layout', 'side');
    expect(readPending('u1')).toEqual({});
  });

  it('a newer choice is not cleared by the older save', () => {
    setPending('u1', 'ui_locale', 'ar');
    setPending('u1', 'ui_locale', 'ur');
    clearPending('u1', 'ui_locale', 'ar');
    expect(readPending('u1')).toEqual({ ui_locale: 'ur' });
    expect(readPending('u2')).toEqual({});
  });
});
