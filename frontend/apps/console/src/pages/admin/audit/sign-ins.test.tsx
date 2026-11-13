import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { SignInLogPage } from '@supportx/api-client';
import { fakeAuditStatus, fakePermissions } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi, fakeSession } from '../../../test/api';

// WP-057 S1a: Audit › Sign-ins (REQ-AUD-015).

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const PERSON = '01900000-0000-7000-8000-0000000000aa';
const PAGE: SignInLogPage = {
  items: [
    {
      id: '01900000-0000-7000-8000-0000000000e1',
      occurred_at: '2026-11-12T09:30:00Z',
      outcome: 'failed',
      reason: 'ip_not_allowed',
      method: 'unknown',
      app: 'console',
      user_id: PERSON,
      ip: '198.51.100.4',
      device: 'chrome:windows',
      identity_provider: null,
    },
    {
      id: '01900000-0000-7000-8000-0000000000e2',
      occurred_at: '2026-11-12T09:00:00Z',
      outcome: 'success',
      reason: null,
      method: 'mobile',
      app: 'mobile',
      user_id: null,
      ip: null,
      device: null,
      identity_provider: null,
    },
  ],
  people: { [PERSON]: { display_name: 'Tariq Technician', email: 'tech@demo.test' } },
  next_cursor: null,
};

function api() {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/audit/status': { body: fakeAuditStatus() },
      'GET /api/v1/identity/sign-ins': { body: PAGE },
    },
  });
  restore = fake.restore;
  return fake;
}

describe('the sign-in log', () => {
  it('REQ-AUD-015: lists sign-ins in words, never codes', async () => {
    window.history.pushState({}, '', '/admin/audit?tab=sign_ins');
    api();
    render(<App />);
    const table = await screen.findByTestId('sign-ins-table');
    await within(table).findByText('Tariq Technician');
    for (const words of [
      'Network not allowed',
      'Chrome on Windows',
      'Not a known person',
      'Mobile app',
      '198.51.100.4',
    ]) {
      expect(within(table).getAllByText(words).length).toBeGreaterThan(0);
    }
    expect(table.textContent).not.toMatch(/ip_not_allowed|chrome:windows|sign_in_/);
  });

  it('REQ-AUD-015 AC2: "failed" in the last 24 hours asks for exactly that', async () => {
    window.history.pushState({}, '', '/admin/audit?tab=sign_ins');
    const fake = api();
    render(<App />);
    await screen.findByTestId('sign-ins-table');
    fireEvent.mouseDown(within(screen.getByTestId('sign-ins-outcome')).getByRole('combobox'));
    fireEvent.click(await screen.findByTitle('Failed'));
    fireEvent.mouseDown(within(screen.getByTestId('sign-ins-period')).getByRole('combobox'));
    fireEvent.click(await screen.findByTitle('Last 24 hours'));
    await waitFor(() => {
      const last = fake.find('GET', '/api/v1/identity/sign-ins').at(-1);
      expect(last?.url.searchParams.getAll('outcome')).toEqual(['failed']);
      const since = new Date(last?.url.searchParams.get('since') ?? '').getTime();
      expect(Date.now() - since).toBeGreaterThan(23.9 * 3600_000);
      expect(Date.now() - since).toBeLessThan(24.1 * 3600_000);
    });
  });

  it('someone with only the sign-in right sees that tab alone', async () => {
    window.history.pushState({}, '', '/admin/audit');
    const fake = consoleApi({
      me: fakeSession(
        { roles: ['technician'] },
        {
          permissions: [
            ...fakePermissions('technician'),
            { key: 'identity.view_sign_ins', scope: 'all', scopes: ['all'], conditional: false },
          ],
        },
      ),
      routes: {
        'GET /api/v1/audit/status': { body: fakeAuditStatus() },
        'GET /api/v1/identity/sign-ins': { body: PAGE },
      },
    });
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByTestId('sign-ins-table')).toBeTruthy();
    expect(screen.queryByRole('tab', { name: 'Integrity' })).toBeNull();
  });
});
