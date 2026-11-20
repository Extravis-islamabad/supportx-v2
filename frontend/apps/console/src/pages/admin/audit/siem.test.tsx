import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { SiemDestination } from '@supportx/api-client';
import { fakeSession } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-057 S5a (REQ-AUD-011): Admin › Audit › Security monitoring. Health in words (never a code),
// the tab only for the audit's managers.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const MANAGER = fakeSession({ roles: ['tenant_admin'] });

const FAILING: SiemDestination = {
  id: '01900000-0000-7000-8000-0000000000c1',
  name: 'Splunk',
  kind: 'syslog',
  format: 'cef',
  host: 'siem.example.test',
  port: 6514,
  url: null,
  streams: ['audit', 'sign_ins'],
  enabled: true,
  has_secret: false,
  rotating: false,
  has_ca: true,
  has_client_cert: false,
  health: {
    behind: 12,
    last_success_at: '2026-11-20T09:00:00Z',
    last_error_code: 'tls',
    last_error_at: '2026-11-20T10:00:00Z',
    failing_since: '2026-11-20T09:30:00Z',
  },
  version: 3,
};

describe('Admin › Audit › Security monitoring', () => {
  it('lists destinations with their health in words, never a code', async () => {
    const fake = consoleApi({
      me: MANAGER,
      routes: { 'GET /api/v1/audit/siem/destinations': { body: [FAILING] } },
    });
    restore = fake.restore;
    window.history.pushState({}, '', '/admin/audit?tab=siem');
    render(<App />);
    const tab = await screen.findByTestId('siem-tab');
    await waitFor(() => {
      expect(within(tab).getByText('Splunk')).toBeDefined();
    });
    expect(tab.textContent).toContain('Syslog over TLS · CEF');
    expect(tab.textContent).toContain('Audit log, Sign-ins');
    expect(tab.textContent).toContain('The secure connection failed');
    expect(tab.textContent).not.toMatch(/\btls\b|siem_error|sign_ins/);
  });

  it('is not offered without audit.manage', async () => {
    const viewer = fakeSession(
      { roles: ['auditor'] },
      { permissions: [{ key: 'audit.view', scope: 'all', scopes: ['all'], conditional: false }] },
    );
    const fake = consoleApi({ me: viewer });
    restore = fake.restore;
    window.history.pushState({}, '', '/admin/audit?tab=siem');
    render(<App />);
    const tabs = await screen.findByTestId('audit-tabs');
    expect(tabs.textContent).not.toContain('Security monitoring');
    expect(screen.queryByTestId('siem-tab')).toBeNull();
    fireEvent.click(tabs); // no crash: the fallback tab shows
  });
});
