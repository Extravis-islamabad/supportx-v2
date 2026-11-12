import { describe, expect, it } from 'vitest';

import { settingsKey } from './incidentSettings';
import { queryKeys } from './keys';
import { releaseKeys } from './releases';
import { stagedKeys } from './staged';

// The settings saves write the cache the screens read (WP-058b S4, lane A's #428 review): the
// release key is spelled out in incidentSettings.ts, so it is pinned to the others here.
describe('settingsKey', () => {
  it('is the incident catalogue for incidents', () => {
    expect(settingsKey('incidents')).toEqual(queryKeys.incidents.catalogue);
  });

  it('is the staged and release settings key for releases', () => {
    expect(settingsKey('releases')).toEqual(stagedKeys('releases').settings);
    expect(settingsKey('releases')).toEqual(releaseKeys.settings);
  });
});
