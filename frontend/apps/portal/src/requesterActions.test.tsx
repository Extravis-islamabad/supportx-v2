import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { PortalIncident } from '@supportx/api-client';
import { fakeApi, fakeEntitlements, fakeSession } from '@supportx/api-client/testing';

import { App } from './App';

// WP-046b S5 (REQ-INC-148): what a requester may still do on their own incident.

const ID = '01a1a2b3-0000-7000-8000-000000000051';
const DETAIL = `/api/v1/portal/incidents/${ID}`;

function mine(over: Partial<PortalIncident> = {}): PortalIncident {
  return {
    id: ID,
    display_id: 'INC-51',
    subject: 'Laptop fan is loud',
    portal_status: 'in_progress',
    reach: 'own',
    requester_id: '01a1a2b3-0000-7000-8000-0000000000aa',
    created_at: '2026-11-03T09:00:00Z',
    updated_at: '2026-11-03T10:00:00Z',
    version: 4,
    description: '<p>Since Monday.</p>',
    may_cancel: 'off',
    editable_fields: [],
    cancellation: null,
    ...over,
  };
}

function routes(item: PortalIncident, extra: Record<string, unknown> = {}) {
  return {
    'GET /api/v1/auth/me': { body: fakeSession({ user_type: 'requester', roles: ['requester'] }) },
    'GET /api/v1/entitlements': { body: fakeEntitlements() },
    'GET /api/v1/announcements/feed': { body: { items: [], next_change_in_seconds: null } },
    [`GET ${DETAIL}`]: { body: item },
    [`GET ${DETAIL}/conversation`]: { body: { items: [] } },
    ...extra,
  };
}

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

describe('portal: cancel and edit your own incident (WP-046b S5)', () => {
  it('off and none: nothing extra on the page (as today)', async () => {
    window.history.pushState({}, '', `/requests/${ID}`);
    const fake = fakeApi(routes(mine()));
    restore = fake.restore;
    render(<App />);
    await screen.findByText('Laptop fan is loud');
    expect(screen.queryByTestId('portal-requester-actions')).toBeNull();
  });

  it('asks to cancel with a reason, and says so once asked', async () => {
    window.history.pushState({}, '', `/requests/${ID}`);
    const fake = fakeApi(
      routes(mine({ may_cancel: 'ask' }), {
        [`POST ${DETAIL}/cancel`]: { body: { canceled: false, request_id: 'r-1' } },
      }),
    );
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('portal-cancel-open'));
    expect(screen.getByTestId('portal-cancel-open').textContent).toBe('Ask to cancel');
    fireEvent.change(await screen.findByTestId('portal-cancel-reason'), {
      target: { value: 'It stopped by itself.' },
    });
    fireEvent.click(screen.getByTestId('portal-cancel-send'));
    await waitFor(() => {
      expect(fake.find('POST', `${DETAIL}/cancel`)[0]?.body).toEqual({
        reason: 'It stopped by itself.',
      });
    });
  });

  it('a waiting ask shows with Take it back', async () => {
    window.history.pushState({}, '', `/requests/${ID}`);
    const fake = fakeApi(
      routes(
        mine({
          may_cancel: 'ask',
          cancellation: { reason: 'Not needed now.', asked_at: '2026-11-21T08:00:00Z' },
        }),
        { [`DELETE ${DETAIL}/cancel-request`]: { status: 204 } },
      ),
    );
    restore = fake.restore;
    render(<App />);
    const asked = await screen.findByTestId('portal-cancel-asked');
    expect(asked.textContent).toContain('Not needed now.');
    expect(screen.queryByTestId('portal-cancel-open')).toBeNull();
    fireEvent.click(screen.getByTestId('portal-cancel-withdraw'));
    await waitFor(() => {
      expect(fake.find('DELETE', `${DETAIL}/cancel-request`)).toHaveLength(1);
    });
  });

  it('edits the allowed fields with the version read (If-Match)', async () => {
    window.history.pushState({}, '', `/requests/${ID}`);
    const fake = fakeApi(
      routes(mine({ editable_fields: ['subject'] }), {
        [`PATCH ${DETAIL}`]: {
          body: mine({ subject: 'Laptop fan is loud (model X1)', version: 5 }),
        },
      }),
    );
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('portal-edit-open'));
    fireEvent.change(screen.getByTestId('portal-edit-subject'), {
      target: { value: 'Laptop fan is loud (model X1)' },
    });
    fireEvent.click(screen.getByTestId('portal-edit-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', DETAIL)).toHaveLength(1);
    });
    const sent = fake.find('PATCH', DETAIL)[0];
    expect(sent?.body).toEqual({ changes: { subject: 'Laptop fan is loud (model X1)' } });
    expect(sent?.headers.get('If-Match')).toBe('"4"');
  });
});
