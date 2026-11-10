import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// REQ-AST-025: the assets an incident is about, in its panel.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
const ITEM = fakeIncident({
  operations: fakeIncident().operations.map((o) =>
    o.action === 'edit' ? { ...o, allowed: true, reason: null } : o,
  ),
});
const PATH = `/api/v1/incidents/${ITEM.id}`;
const LAPTOP = '01900000-0000-7000-8000-0000000a5e01';
const GONE = '01900000-0000-7000-8000-0000000a5e02';
const HIDDEN = '01900000-0000-7000-8000-0000000a5e03';
const link = (assetId: string, extra: Record<string, unknown>) => ({
  id: `l-${assetId}`,
  asset_id: assetId,
  tag: null,
  name: null,
  gone: false,
  hidden: false,
  mine: false,
  source: 'ui',
  version: 2,
  created_at: '2026-11-10T09:00:00Z',
  ...extra,
});
const COMMON = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/organization/groups': { body: [] },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
  [`GET ${PATH}`]: { body: ITEM },
  [`GET ${PATH}/assets`]: {
    body: {
      items: [
        link(LAPTOP, { tag: 'AST-12', name: 'Dell laptop' }),
        link(GONE, { gone: true }),
        link(HIDDEN, { hidden: true }),
      ],
    },
  },
};

describe('REQ-AST-025: an incident’s assets', () => {
  beforeEach(() => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
  });
  afterEach(() => {
    restore();
  });

  it('lists them as you may see them, and unlinks with the version shown', async () => {
    const fake = api({
      routes: { ...COMMON, [`DELETE ${PATH}/assets/l-${LAPTOP}`]: { status: 204 } },
    });
    render(<App />);
    const section = await screen.findByTestId('incidents-assets');
    await waitFor(() => {
      expect(within(section).getByTestId(`record-asset-${LAPTOP}`).textContent).toBe(
        'AST-12 · Dell laptop',
      );
    });
    // A removed or hidden asset says so, never named and never an ID.
    expect(within(section).getByTestId(`record-asset-${GONE}`).textContent).toBe('A removed asset');
    expect(within(section).getByTestId(`record-asset-${HIDDEN}`).textContent).toBe(
      'An asset you may not see',
    );
    expect(section.textContent).not.toContain(GONE);
    // The Link button says why it waits.
    expect(screen.getByTestId('incidents-assets-link')).toHaveProperty('disabled', true);
    fireEvent.click(within(section).getByTestId(`record-asset-remove-${LAPTOP}`));
    await waitFor(() => {
      expect(fake.find('DELETE', `${PATH}/assets/l-${LAPTOP}`)).toHaveLength(1);
    });
    expect(fake.find('DELETE', `${PATH}/assets/l-${LAPTOP}`)[0]?.headers.get('If-Match')).toBe(
      '"2"',
    );
  });
});
