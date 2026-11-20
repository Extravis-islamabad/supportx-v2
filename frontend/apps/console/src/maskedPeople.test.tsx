import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeIncidentCatalogue, fakeSession } from '@supportx/api-client/testing';

import { App } from './App';
import { consoleApi } from './test/api';

// WP-057 S4c-3, D-180 (lane A's #566 condition 3): a support session whose grant masks names
// sees the labelled stand-in wherever a record shows a person, never an empty name; a session
// that doesn't mask sees the name. One case per module family: incidents, requests, problems.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const REQUESTER = '01900000-0000-7000-8000-0000000002a1';

function supportSession(namesMasked: boolean) {
  const base = fakeSession({ roles: ['technician'] }); // its grant's rights, as a role here
  return {
    ...base,
    user: { ...base.user, user_type: 'vendor_support' as const },
    support: {
      grant_id: '01900000-0000-7000-8000-0000000000aa',
      access: 'view' as const,
      ends_at: '2099-01-01T10:00:00Z',
      contacts_masked: true,
      names_masked: namesMasked,
    },
  };
}

function withRequester(name: string) {
  return { [REQUESTER]: { display_name: name, email: '' } };
}

describe('names withheld from a masked support session', () => {
  it('incidents: the record and the list say "Person hidden"', async () => {
    const item = fakeIncident({ people: withRequester('') });
    const fake = consoleApi({
      me: supportSession(true),
      routes: {
        'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
        [`GET /api/v1/incidents/${item.id}`]: { body: item },
        'GET /api/v1/incidents': {
          body: {
            items: [{ ...item, deleted_at: null }],
            next_cursor: null,
            has_more: false,
            estimated_total: 1,
            people: withRequester(''),
          },
        },
        'GET /api/v1/incidents/categories': { body: [] },
        'GET /api/v1/organization/groups': { body: [] },
        'GET /api/v1/organization/sites': { body: [] },
        'GET /api/v1/incidents/views': { body: [{ view: 'open', count: 1, capped: false }] },
        'GET /api/v1/incidents/list-fields': { body: [] },
        'GET /api/v1/incidents/saved-views': { body: [] },
        'GET /api/v1/incidents/view-filters': {
          body: [{ view: 'open', expressible: true, filter: null }],
        },
        'GET /api/v1/incidents/list-settings/open': {
          body: {
            view_key: 'open',
            columns: ['display_id', 'subject', 'requester_id'],
            sort: null,
            page_size: 50,
            version: null,
          },
        },
      },
    });
    restore = fake.restore;
    window.history.pushState({}, '', `/incidents/${item.id}`);
    const record = render(<App />);
    await waitFor(() => {
      expect(document.body.textContent).toContain('Person hidden');
    });
    record.unmount();
    window.history.pushState({}, '', '/incidents');
    render(<App />);
    await screen.findByTestId(`inc-row-${item.display_id}`);
    const list = screen.getByTestId('inc-table');
    await waitFor(() => {
      expect(list.textContent).toContain('Person hidden');
    });
  });

  it('requests: the record says "Person hidden"', async () => {
    const item = fakeIncident({
      id: '01900000-0000-7000-8000-00000000c501',
      type: 'service_request',
      display_id: 'SR-1',
      people: withRequester(''),
    });
    const fake = consoleApi({
      me: supportSession(true),
      routes: {
        [`GET /api/v1/service-requests/${item.id}`]: { body: item },
        [`GET /api/v1/service-requests/${item.id}/approvals`]: { body: { items: [], people: {} } },
        [`GET /api/v1/service-requests/${item.id}/tasks`]: {
          body: { items: [], done: 0, total: 0 },
        },
      },
    });
    restore = fake.restore;
    window.history.pushState({}, '', `/requests/${item.id}`);
    render(<App />);
    expect(await screen.findByTestId('sr-requester')).toBeDefined();
    await waitFor(() => {
      expect(screen.getByTestId('sr-requester').textContent).toBe('Person hidden');
    });
  });

  it('problems: the record says "Person hidden", and a session that doesn\'t mask sees the name', async () => {
    const item = fakeIncident({
      id: '01900000-0000-7000-8000-00000000e001',
      type: 'problem',
      display_id: 'PRB-7',
      people: withRequester(''),
    });
    const routes = {
      'GET /api/v1/problems/settings': { body: fakeIncidentCatalogue() },
      [`GET /api/v1/problems/${item.id}`]: { body: item },
      [`GET /api/v1/problems/${item.id}/links`]: { body: [] },
    };
    const fake = consoleApi({ me: supportSession(true), routes });
    restore = fake.restore;
    window.history.pushState({}, '', `/problems/${item.id}`);
    const masked = render(<App />);
    await screen.findByTestId('prb-record');
    await waitFor(() => {
      expect(screen.getByTestId('prb-record').textContent).toContain('Person hidden');
    });
    masked.unmount();
    restore();
    const shown = consoleApi({
      me: supportSession(false),
      routes: {
        ...routes,
        [`GET /api/v1/problems/${item.id}`]: {
          body: { ...item, people: withRequester('Rana Requester') },
        },
      },
    });
    restore = shown.restore;
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId('prb-record').textContent).toContain('Rana Requester');
    });
    expect(screen.getByTestId('prb-record').textContent).not.toContain('Person hidden');
  });
});
