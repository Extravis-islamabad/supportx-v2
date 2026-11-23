import { render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { SystemLogEntry } from '@supportx/api-client';
import { fakeAuditStatus } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi, fakeSession } from '../../../test/api';

// WP-057 S5b (REQ-AUD-016): Audit › System log. Codes in words (never raw), the object linked,
// and the export only for audit.export holders.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const ADMIN = fakeSession({ roles: ['tenant_admin'] });

const FAILED: SystemLogEntry = {
  id: '01900000-0000-7000-8000-00000000c501',
  occurred_at: '2026-11-20T10:00:00Z',
  severity: 'error',
  module: 'integrations',
  code: 'integrations.mailbox.check_failed',
  params: {},
  object_type: 'mailbox',
  object_id: '01900000-0000-7000-8000-00000000c502',
  job_id: 'mail-poll-1',
  request_id: null,
};
const PURGED: SystemLogEntry = {
  ...FAILED,
  id: '01900000-0000-7000-8000-00000000c503',
  severity: 'info',
  module: 'audit',
  code: 'audit.system_log.purged',
  params: { entries: 12 },
  object_type: null,
  object_id: null,
  job_id: null,
};

describe('Audit › System log', () => {
  it('shows each entry in words, links its object and offers the export', async () => {
    window.history.pushState({}, '', '/admin/audit?tab=system_log');
    const fake = consoleApi({
      me: ADMIN,
      routes: {
        'GET /api/v1/audit/status': { body: fakeAuditStatus() },
        'GET /api/v1/audit/system-log': { body: { items: [FAILED, PURGED], next_after: null } },
      },
    });
    restore = fake.restore;
    render(<App />);
    const tab = await screen.findByTestId('system-log');
    await waitFor(() => {
      expect(within(tab).getByText('Checking a mailbox for new mail failed')).toBeTruthy();
    });
    expect(tab.textContent).toContain('12 system log entries past retention were removed');
    expect(tab.textContent).toContain('Error');
    expect(tab.textContent).toContain('Integrations');
    expect(within(tab).getByRole('link', { name: 'Mailbox' }).getAttribute('href')).toBe(
      '/admin/mail',
    );
    expect(tab.textContent).not.toMatch(/check_failed|system_log\.|integrations\./);
    expect(within(tab).getByTestId('system-log-export')).toBeTruthy();
  });
});
