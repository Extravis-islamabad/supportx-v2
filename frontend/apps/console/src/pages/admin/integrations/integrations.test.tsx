import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { ConnectorKind } from '@supportx/api-client';
import { fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-040: Admin › Integrations (REQ-INT-001, REQ-INT-004, REQ-INT-013).
let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const CATALOGUE = '/api/v1/integrations/catalogue';
const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const TECH = fakeSession({ display_name: 'Tariq Tech', roles: ['technician'] });

function mailboxKind(over: Partial<ConnectorKind> = {}): ConnectorKind {
  return {
    code: 'mailbox',
    category: 'email',
    page: '/admin/mail',
    keywords: ['connector_keyword.imap', 'connector_keyword.oauth', 'connector_keyword.key'],
    reason_labels: 'mailbox_reason',
    multiple: true,
    available: true,
    can_manage: true,
    manage_reason: null,
    instances: [
      {
        id: 'mb-1',
        name: 'it@acme.test',
        status: 'active',
        reason: null,
        last_success_at: '2026-11-02T09:00:00Z',
        next_run_at: null,
        credential_expires_at: null,
        failing_since: null,
        last_error_at: null,
        last_error_code: null,
        counts_24h: { runs: 12, failed_runs: 0, read: 30 },
      },
    ],
    ...over,
  };
}

describe('Admin › Integrations', () => {
  afterEach(() => {
    restore();
    setDefaultClientFactory(inertClientFactory);
  });

  it('lists connectors by category with their status, and finds them by keyword', async () => {
    window.history.pushState({}, '', '/admin/integrations');
    api({ me: ADMIN, routes: { [`GET ${CATALOGUE}`]: { body: [mailboxKind()] } } });
    render(<App />);
    const email = await screen.findByTestId('connector-category-email');
    expect(within(email).getByText('Email')).toBeTruthy();
    const instance = within(email).getByTestId('connector-instance-mb-1');
    expect(within(instance).getByTestId('connector-status').textContent).toBe('Active');
    expect(instance.textContent).toContain('Last 24 hours: 12 runs, 30 items read, 0 failed runs');
    const search = screen.getByLabelText('Search by name or keyword, such as key or API');
    fireEvent.change(search, { target: { value: 'key' } }); // REQ-INT-001 AC1
    expect(screen.getByTestId('connector-kind-mailbox')).toBeTruthy();
    fireEvent.change(search, { target: { value: 'webhook' } });
    expect(await screen.findByText('No connector matches this search.')).toBeTruthy();
  });

  it('reads right to left in Arabic, with the address kept whole', async () => {
    window.history.pushState({}, '', '/admin/integrations');
    api({
      me: fakeSession({ roles: ['tenant_admin', 'technician'], locale: 'ar' }),
      routes: { [`GET ${CATALOGUE}`]: { body: [mailboxKind()] } },
    });
    render(<App />);
    const email = await screen.findByTestId('connector-category-email');
    expect(within(email).getByText('البريد الإلكتروني')).toBeTruthy();
    expect(within(email).getByTestId('connector-status').textContent).toBe('نشط');
    await waitFor(() => {
      expect(document.documentElement.getAttribute('dir')).toBe('rtl');
    });
    expect(within(email).getByText('it@acme.test').tagName).toBe('BDI');
  });

  it('is read-only with the reason for someone without set-up rights', async () => {
    window.history.pushState({}, '', '/admin/integrations');
    api({
      me: TECH,
      routes: {
        [`GET ${CATALOGUE}`]: {
          body: [mailboxKind({ can_manage: false, manage_reason: 'no_permission' })],
        },
      },
    });
    render(<App />);
    const card = await screen.findByTestId('connector-kind-mailbox');
    expect(within(card).getByTestId('connector-set-up').hasAttribute('disabled')).toBe(true);
    expect(within(card).getByTestId('connector-read-only').textContent).toBe(
      'You do not have permission to set up this connector.',
    );
  });

  it('REQ-INT-001 AC3: a failing mailbox shows as failed without a reload', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', '/admin/integrations');
    let kind = mailboxKind();
    const fake = api({ me: ADMIN, routes: { [`GET ${CATALOGUE}`]: () => ({ body: [kind] }) } });
    render(<App />);
    await screen.findByTestId('connector-instance-mb-1');
    const [working] = mailboxKind().instances;
    if (working === undefined) throw new Error('the fixture has an instance');
    kind = mailboxKind({
      instances: [
        {
          ...working,
          status: 'failed',
          reason: 'imap_login_failed',
          last_success_at: null,
        },
      ],
    });
    const before = fake.find('GET', CATALOGUE).length;
    act(() => {
      realtime.publish(':broadcast', { type: 'integrations.connectors_changed', ids: [] });
    });
    await waitFor(() => {
      expect(fake.find('GET', CATALOGUE).length).toBeGreaterThan(before);
    });
    const instance = await screen.findByTestId('connector-instance-mb-1');
    await waitFor(() => {
      expect(within(instance).getByTestId('connector-status').textContent).toBe('Failed');
    });
    expect(instance.textContent).toContain('The mail server refused the user name or password');
  });
});
