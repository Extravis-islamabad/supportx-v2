import { render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import {
  fakeEntitlements,
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
} from '@supportx/api-client/testing';
import { documentTitle } from '@supportx/ui';

import { App } from './App';
import { consoleApi, fakeSession } from './test/api';

// The header says where you are, not "Technician Console" (product owner, 2026-10-28): breadcrumbs
// of the page (the record's desk first when ESM is on) and the same in the browser tab.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const SIDE = fakeSession({ nav_layout: 'side' }); // the header holds the breadcrumbs
const ITEM = fakeIncident({ display_id: 'INC-42' });
const PATH = `/api/v1/incidents/${ITEM.id}`;
const DESK = {
  id: ITEM.desk_id,
  code: 'it',
  labels: { en: 'IT Service Desk', ar: 'مكتب خدمة تقنية المعلومات' },
  is_default: true,
  disabled: false,
  version: 1,
  created_at: '2026-10-01T00:00:00Z',
};
const ROUTES = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/organization/groups': { body: [] },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/organization/departments': { body: [] },
  'GET /api/v1/organization/desks': { body: [DESK] },
  'GET /api/v1/custom-fields': { body: [] },
  'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
  [`GET ${PATH}`]: { body: ITEM, headers: { ETag: `"${String(ITEM.version)}"` } },
  [`GET ${PATH}/conversation`]: { body: { items: [], people: {} } },
  [`GET ${PATH}/automation`]: { body: [] },
  'GET /api/v1/incidents': { body: { items: [], has_more: false, next_cursor: null, total: 0 } },
  'GET /api/v1/incidents/views': { body: [] },
};

afterEach(() => {
  restore();
});

describe('where you are, in the header and the tab', () => {
  it('the tab reads newest first, ending in the product', () => {
    expect(
      documentTitle([{ label: 'Incidents', path: '/incidents' }, { label: 'INC-42' }], 'SupportX'),
    ).toBe('INC-42 · Incidents · SupportX');
    expect(documentTitle([], 'SupportX')).toBe('SupportX');
  });

  it('a section shows its name; "Technician Console" is gone', async () => {
    window.history.pushState({}, '', '/incidents');
    api({ me: SIDE, routes: ROUTES });
    render(<App />);
    const crumbs = await screen.findByTestId('header-crumbs');
    expect(crumbs.textContent).toBe('Incidents');
    await waitFor(() => {
      expect(document.title).toBe('Incidents · SupportX');
    });
    expect(document.body.textContent).not.toContain('Technician Console');
  });

  it('a record: its desk (ESM on), the section as a link and the record; the tab follows', async () => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    api({ me: SIDE, routes: ROUTES });
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId('header-crumbs').textContent).toBe(
        'IT Service Desk/Incidents/INC-42',
      );
    });
    const crumbs = screen.getByTestId('header-crumbs');
    expect(within(crumbs).getByRole('link', { name: 'Incidents' }).getAttribute('href')).toBe(
      '/incidents',
    );
    expect(within(crumbs).getByText('INC-42').closest('[aria-current="page"]')).not.toBeNull();
    expect(screen.getByRole('navigation', { name: 'You are here' })).toBeDefined();
    await waitFor(() => {
      expect(document.title).toBe('INC-42 · Incidents · IT Service Desk · SupportX');
    });
  });

  it('without ESM there is no desk', async () => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    const features = fakeEntitlements().features.filter((f) => f !== 'esm');
    api({
      me: SIDE,
      routes: {
        ...ROUTES,
        'GET /api/v1/entitlements': { body: fakeEntitlements({ features }) },
      },
    });
    render(<App />);
    await waitFor(() => {
      expect(document.title).toBe('INC-42 · Incidents · SupportX');
    });
    expect(screen.getByTestId('header-crumbs').textContent).toBe('Incidents/INC-42');
  });

  it('with the top menu, a record says where it is above the page; a section alone does not', async () => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    api({ routes: ROUTES }); // the suite's session: top menu
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId('header-crumbs').textContent).toBe(
        'IT Service Desk/Incidents/INC-42',
      );
    });
    expect(screen.getByTestId('header-crumbs').closest('header')).toBeNull(); // not in the header
    expect(document.body.textContent).not.toContain('Technician Console');
  });
});
