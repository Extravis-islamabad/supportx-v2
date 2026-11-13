import { render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeAuditStatus, fakePermissions } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi, fakeSession } from '../../../test/api';

// WP-057 S3b-1 (REQ-AUD-017): Audit › Personal data access, for someone who holds only that right.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

// A technician given only the access-log right (a DPO-style role; lane B).
const DPO = fakeSession(
  { display_name: 'Dana Protection', roles: ['technician'] },
  {
    permissions: [
      ...fakePermissions('technician'),
      { key: 'audit.view_personal_data_access', scope: 'all', scopes: ['all'], conditional: false },
    ],
  },
);

describe('Audit › Personal data access', () => {
  it('a holder of only the access-log right sees that tab alone, and must choose a person', async () => {
    window.history.pushState({}, '', '/admin/audit');
    const fake = consoleApi({
      me: DPO,
      routes: { 'GET /api/v1/audit/status': { body: fakeAuditStatus() } },
    });
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByTestId('personal-data-access')).toBeTruthy();
    const tabs = within(screen.getByTestId('audit-tabs')).getAllByRole('tab');
    expect(tabs.map((tab) => tab.textContent)).toEqual(['Personal data access']);
    expect(
      screen.getByText('Choose a person to see who accessed their personal data.'),
    ).toBeTruthy();
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/audit/personal-data-access')).toHaveLength(0);
    });
  });
});
