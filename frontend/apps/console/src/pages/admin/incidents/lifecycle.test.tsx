import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncidentCatalogue, fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// Admin › Incidents › Life cycle (ADR-049; WP-046a S4a, REQ-INC-049): versions, the draft's
// moves, problems by name, and publishing that says records keep their version.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const ADMIN = fakeSession({ roles: ['tenant_admin'] });
const BASE = '/api/v1/incidents/settings/lifecycles/standard';
const MOVE = {
  from_status: 'new',
  action: 'start_work',
  to_status: 'in_progress',
  reason_mode: 'none',
  reason_list: null,
  permission: null,
  required_fields: [],
};
const PUBLISHED = {
  number: 1,
  state: 'published',
  published_at: '2026-11-01T09:00:00Z',
  published_by: null,
  problems: [],
  moves: 40,
};

function routes(versions: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  return {
    'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
    'GET /api/v1/permissions': { body: [] },
    'GET /api/v1/custom-fields': { body: [] },
    [`GET ${BASE}/versions`]: { body: versions },
    ...extra,
  } as NonNullable<Parameters<typeof consoleApi>[0]>['routes'];
}

describe('Admin › Incidents › Life cycle', () => {
  it('lists the versions, marks where new records start, and starts a draft with If-Match', async () => {
    const fake = api({
      me: ADMIN,
      routes: routes(
        { lifecycle: 'standard', latest_published: 1, settings_version: 7, items: [PUBLISHED] },
        { [`POST ${BASE}/versions`]: { status: 201, body: { number: 2, problems: [] } } },
      ),
    });
    window.history.pushState({}, '', '/admin/incidents/lifecycle');
    render(<App />);
    const card = await screen.findByTestId('lifecycle-versions');
    expect((await within(card).findByTestId('lifecycle-version-1')).textContent).toBe('Version 1');
    expect(card.textContent).toContain('New records start here');
    expect(card.textContent).toContain('Published');
    fireEvent.click(await screen.findByTestId('lifecycle-start'));
    await waitFor(() => {
      expect(fake.find('POST', `${BASE}/versions`)).toHaveLength(1);
    });
    expect(fake.find('POST', `${BASE}/versions`)[0]?.headers.get('If-Match')).toBe('"7"');
  });

  it('REQ-INC-049 AC1: a draft names its problems in words, and publishing says records keep their version', async () => {
    api({
      me: ADMIN,
      routes: routes(
        {
          lifecycle: 'standard',
          latest_published: 1,
          settings_version: 8,
          items: [
            {
              ...PUBLISHED,
              number: 2,
              state: 'draft',
              published_at: null,
              problems: [{ code: 'status_no_way_out', params: { status: 'in_progress' } }],
              moves: 1,
            },
            PUBLISHED,
          ],
        },
        { [`GET ${BASE}/versions/2/moves`]: { body: [MOVE] } },
      ),
    });
    window.history.pushState({}, '', '/admin/incidents/lifecycle');
    render(<App />);
    const problems = await screen.findByTestId('lifecycle-problems');
    expect(problems.textContent).toContain('In progress has no way out');
    expect(problems.textContent).not.toContain('in_progress');
    // With a problem left, publishing is not offered.
    expect(screen.getByTestId('lifecycle-publish').hasAttribute('disabled')).toBe(true);
  });

  it('the publish dialog says existing records stay on their version (until S4b migrates them)', async () => {
    const fake = api({
      me: ADMIN,
      routes: routes(
        {
          lifecycle: 'standard',
          latest_published: 1,
          settings_version: 9,
          items: [{ ...PUBLISHED, number: 2, state: 'draft', published_at: null }, PUBLISHED],
        },
        {
          [`GET ${BASE}/versions/2/moves`]: { body: [MOVE] },
          [`POST ${BASE}/draft/publish`]: {
            body: { lifecycle: 'standard', latest_published: 2, settings_version: 10, items: [] },
          },
        },
      ),
    });
    window.history.pushState({}, '', '/admin/incidents/lifecycle');
    render(<App />);
    fireEvent.click(await screen.findByTestId('lifecycle-publish'));
    const body = await screen.findByTestId('lifecycle-confirm-publish');
    expect(body.textContent).toContain(
      'Existing records stay on the version they started on and keep its moves.',
    );
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Publish' }));
    await waitFor(() => {
      expect(fake.find('POST', `${BASE}/draft/publish`)).toHaveLength(1);
    });
    expect(fake.find('POST', `${BASE}/draft/publish`)[0]?.headers.get('If-Match')).toBe('"9"');
  });

  it("another admin's change reaches the screen live", async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    const fake = api({
      me: ADMIN,
      routes: routes({
        lifecycle: 'standard',
        latest_published: 1,
        settings_version: 7,
        items: [PUBLISHED],
      }),
    });
    window.history.pushState({}, '', '/admin/incidents/lifecycle');
    render(<App />);
    await screen.findByTestId('lifecycle-version-1');
    const before = fake.find('GET', `${BASE}/versions`).length;
    act(() => {
      realtime.publish(':broadcast', { type: 'work_items.settings_changed', ids: [] });
    });
    await waitFor(() => {
      expect(fake.find('GET', `${BASE}/versions`).length).toBeGreaterThan(before);
    });
  });
});
