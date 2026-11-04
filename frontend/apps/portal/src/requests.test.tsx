import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { PortalIncident } from '@supportx/api-client';
import { fakeApi, fakeEntitlements, fakeSession } from '@supportx/api-client/testing';

import { App } from './App';

// WP-028: My requests, one request, and Report an issue, as a requester sees them.

const ID = '01a1a2b3-0000-7000-8000-000000000001';

function portalIncident(over: Partial<PortalIncident> = {}): PortalIncident {
  return {
    id: ID,
    display_id: 'INC-42',
    subject: 'Printer jams on tray 2',
    portal_status: 'in_progress',
    reach: 'own',
    requester_id: '01a1a2b3-0000-7000-8000-0000000000aa',
    created_at: '2026-11-03T09:00:00Z',
    updated_at: '2026-11-03T10:00:00Z',
    version: 3,
    description: '<p>It jams every time.</p>',
    ...over,
  };
}

const BASE = {
  'GET /api/v1/auth/me': { body: fakeSession({ user_type: 'requester', roles: ['requester'] }) },
  'GET /api/v1/entitlements': { body: fakeEntitlements() },
  'GET /api/v1/announcements/feed': { body: { items: [], next_change_in_seconds: null } },
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

describe('portal: my requests', () => {
  it('lists the person’s own requests with the plain status, open first', async () => {
    window.history.pushState({}, '', '/requests');
    const fake = fakeApi({
      ...BASE,
      'GET /api/v1/portal/incidents': {
        body: { items: [portalIncident()], next_cursor: null, has_more: false },
      },
    });
    restore = fake.restore;
    render(<App />);
    const row = await screen.findByTestId('portal-request-INC-42');
    expect(within(row).getByText('Printer jams on tray 2')).toBeDefined();
    expect(within(row).getByTestId('portal-status').textContent).toBe('In progress');
    expect(fake.find('GET', '/api/v1/portal/incidents')[0]?.url.searchParams.get('state')).toBe(
      'open',
    );
    // own reach only: no "whose requests" filter to choose from
    expect(screen.queryByTestId('portal-requests-reach')).toBeNull();
  });

  it('shows the reach filter when the person sees wider than their own', async () => {
    window.history.pushState({}, '', '/requests');
    const fake = fakeApi({
      ...BASE,
      'GET /api/v1/portal/incidents': {
        body: {
          items: [portalIncident({ reach: 'reports', display_id: 'INC-43' })],
          next_cursor: null,
          has_more: false,
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    const row = await screen.findByTestId('portal-request-INC-43');
    expect(within(row).getByText(/My direct reports/)).toBeDefined();
    expect(screen.getByTestId('portal-requests-reach')).toBeDefined();
  });
});

describe('portal: one request', () => {
  it('a resolved request asks the requester to confirm the fix', async () => {
    window.history.pushState({}, '', `/requests/${ID}`);
    const resolved = portalIncident({ portal_status: 'resolved', resolution: '<p>Reset done</p>' });
    const fake = fakeApi({
      ...BASE,
      [`GET /api/v1/portal/incidents/${ID}`]: { body: resolved },
      [`GET /api/v1/portal/incidents/${ID}/conversation`]: {
        body: {
          items: [
            {
              id: 'e1',
              kind: 'reply',
              body: '<p>Restart it please.</p>',
              created_at: '2026-11-03T09:30:00Z',
              author_name: 'Sam Tech',
              by_you: false,
            },
          ],
        },
      },
      [`POST /api/v1/portal/incidents/${ID}/resolution/confirm`]: {
        body: portalIncident({ portal_status: 'closed' }),
      },
    });
    restore = fake.restore;
    render(<App />);
    expect((await screen.findByTestId('portal-fix-text')).textContent).toContain('Reset done');
    expect(await screen.findByText('Sam Tech')).toBeDefined();
    fireEvent.click(screen.getByTestId('portal-fix-confirm'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/portal/incidents/${ID}/resolution/confirm`)).toHaveLength(
        1,
      );
    });
    await waitFor(() => {
      expect(screen.queryByTestId('portal-fix')).toBeNull();
    });
  });

  it('a request out of reach reads as not found, in words', async () => {
    window.history.pushState({}, '', `/requests/${ID}`);
    const fake = fakeApi({ ...BASE });
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByText(/does not exist or is not yours to see/)).toBeDefined();
  });
});

describe('portal: report an issue', () => {
  it('sends the subject once, with the form and a key, and opens the new request', async () => {
    window.history.pushState({}, '', '/requests/new');
    const fake = fakeApi({
      ...BASE,
      'GET /api/v1/portal/incidents/templates': {
        body: [
          {
            id: 't1',
            code: 'standard',
            labels: null,
            description: null,
            is_default: true,
            fields: [{ name: 'subject', required: true }],
          },
        ],
      },
      'POST /api/v1/portal/incidents': {
        status: 201,
        body: portalIncident({ portal_status: 'received' }),
      },
      [`GET /api/v1/portal/incidents/${ID}`]: {
        body: portalIncident({ portal_status: 'received' }),
      },
      [`GET /api/v1/portal/incidents/${ID}/conversation`]: { body: { items: [] } },
    });
    restore = fake.restore;
    render(<App />);
    const send = await screen.findByTestId('portal-report-send');
    expect((send as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByTestId('portal-report-subject'), {
      target: { value: '  Laptop will not start ' },
    });
    fireEvent.click(send);
    await waitFor(() => {
      expect(window.location.pathname).toBe(`/requests/${ID}`);
    });
    const [sent] = fake.find('POST', '/api/v1/portal/incidents');
    expect(sent?.body).toEqual({ template_id: 't1', subject: 'Laptop will not start' });
    expect(sent?.headers.get('Idempotency-Key')).toBeTruthy();
    expect((await screen.findByTestId('portal-request-id')).textContent).toBe('INC-42');
  });
});

describe('portal: my requests, long lists', () => {
  it('shows more with the next cursor, keeping the first page', async () => {
    window.history.pushState({}, '', '/requests');
    const fake = fakeApi({
      ...BASE,
      'GET /api/v1/portal/incidents': (call) =>
        call.url.searchParams.get('cursor') === 'c2'
          ? {
              body: {
                items: [portalIncident({ id: 'second', display_id: 'INC-2' })],
                next_cursor: null,
                has_more: false,
              },
            }
          : {
              body: {
                items: [portalIncident({ id: 'first', display_id: 'INC-1' })],
                next_cursor: 'c2',
                has_more: true,
              },
            },
    });
    restore = fake.restore;
    render(<App />);
    await screen.findByTestId('portal-request-INC-1');
    fireEvent.click(screen.getByTestId('portal-requests-more'));
    await screen.findByTestId('portal-request-INC-2');
    expect(screen.getByTestId('portal-request-INC-1')).toBeDefined();
    await waitFor(() => {
      expect(screen.queryByTestId('portal-requests-more')).toBeNull();
    });
  });
});

describe('portal: files on a request', () => {
  const routes = (over: Partial<PortalIncident>) => ({
    ...BASE,
    [`GET /api/v1/portal/incidents/${ID}`]: { body: portalIncident(over) },
    [`GET /api/v1/portal/incidents/${ID}/conversation`]: { body: { items: [] } },
    [`GET /api/v1/files/records/incident/${ID}`]: { body: [] },
  });

  it('their own open request takes files, from the phone camera too', async () => {
    window.history.pushState({}, '', `/requests/${ID}`);
    const fake = fakeApi(routes({}));
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByTestId('portal-files-drop')).toBeDefined();
    const camera = await screen.findByTestId('portal-files-camera');
    const input = camera.closest('.ant-upload')?.querySelector('input[type=file]');
    expect(input?.getAttribute('accept')).toBe('image/*');
    expect(input?.getAttribute('capture')).toBe('environment');
  });

  it('a manager seeing a report’s request reads it but adds nothing', async () => {
    window.history.pushState({}, '', `/requests/${ID}`);
    const fake = fakeApi(routes({ reach: 'reports' }));
    restore = fake.restore;
    render(<App />);
    await screen.findByTestId('portal-request-id');
    expect(screen.queryByTestId('portal-files-drop')).toBeNull();
    expect(screen.queryByTestId('portal-reply')).toBeNull();
  });
});

describe('portal: the expected resolution time', () => {
  it('shows only when the server sends it (the tenant shows it, D5)', async () => {
    window.history.pushState({}, '', `/requests/${ID}`);
    const fake = fakeApi({
      ...BASE,
      [`GET /api/v1/portal/incidents/${ID}`]: {
        body: portalIncident({ resolution_due_at: '2026-11-05T14:00:00Z' }),
      },
      [`GET /api/v1/portal/incidents/${ID}/conversation`]: { body: { items: [] } },
      [`GET /api/v1/files/records/incident/${ID}`]: { body: [] },
    });
    restore = fake.restore;
    render(<App />);
    expect((await screen.findByTestId('portal-due')).textContent).toMatch(/^Expected by /);
  });
});
