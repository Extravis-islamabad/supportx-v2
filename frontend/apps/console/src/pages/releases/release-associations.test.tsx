import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { releaseKeys, type Release } from '@supportx/api-client';
import { fakeIncident, fakeIncidentCatalogue } from '@supportx/api-client/testing';
import { AppearanceProvider, createQueryClient } from '@supportx/ui';

import { consoleApi } from '../../test/api';
import { ReleaseProperties } from './ReleaseProperties';

// REQ-REL-058 (WP-058b S5b): the side panel counts the release's changes and sub-releases, and
// follows the record channel: the page's channel invalidates the release's detail tree, and the
// counts read again (AC3). It only reads: fields change through the edit form (AC2).

const REL_ID = '01a1a2b3-0000-7000-8000-0000000e0001';
const change = (n: number) => ({
  id: `01a1a2b3-0000-7000-8000-0000000e0a0${String(n)}`,
  visible: true,
  display_id: `CHG-${String(n)}`,
  subject: 'Work',
  stage: 'implementation',
  status: 'implementation_scheduled',
  status_category: 'open',
});

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

describe('the release side panel', () => {
  it('REQ-REL-058 AC3: counts its changes and sub-releases, and reads them again when told', async () => {
    let linked = [change(1)];
    const fake = consoleApi({
      routes: {
        'GET /api/v1/releases/settings': { body: fakeIncidentCatalogue() },
        [`GET /api/v1/releases/${REL_ID}/details`]: {
          body: {
            work_item_id: REL_ID,
            version: 1,
            release_type: null,
            risk: null,
            release_version: null,
            build_ref: null,
            release_reason: null,
            release_notes: null,
            scheduled_start: null,
            scheduled_end: null,
            actual_start: null,
            actual_end: null,
            release_manager_id: null,
            release_engineer_id: null,
          },
        },
        [`GET /api/v1/releases/${REL_ID}/changes`]: () => ({ body: linked }),
        [`GET /api/v1/releases/${REL_ID}/sub-releases`]: { body: [] },
      },
    });
    restore = fake.restore;
    const client: QueryClient = createQueryClient();
    const release = {
      ...fakeIncident({ id: REL_ID, display_id: 'REL-1' }),
      type: 'release',
      stage: 'build',
      stage_path: 'standard',
    } as unknown as Release;
    render(
      <QueryClientProvider client={client}>
        <AppearanceProvider>
          <ReleaseProperties id={REL_ID} release={release} />
        </AppearanceProvider>
      </QueryClientProvider>,
    );
    const counts = await screen.findByTestId('release-associations');
    await waitFor(() => {
      expect(
        within(counts).getByText('Changes').closest('div')?.parentElement?.textContent,
      ).toContain('1');
    });
    expect(counts.textContent).toContain('Sub-releases');
    // A change is linked from its own page: the record channel tells the release page, which
    // invalidates the release's detail tree, as here.
    linked = [change(1), change(2)];
    await act(async () => {
      await client.invalidateQueries({ queryKey: releaseKeys.detail(REL_ID) });
    });
    await waitFor(() => {
      expect(fake.find('GET', `/api/v1/releases/${REL_ID}/changes`).length).toBeGreaterThan(1);
    });
    await waitFor(() => {
      expect(screen.getByTestId('release-associations').textContent).toContain('2');
    });
  });
});
