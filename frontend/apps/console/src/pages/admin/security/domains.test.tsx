import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { VerifiedDomain } from '@supportx/api-client';
import { fakeSession } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-057 S5d (REQ-SEC-010): Sign-in and security › Verified domains. States in words, the record
// shown once after adding, never a raw code.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const ADMIN = fakeSession({ roles: ['tenant_admin'] });

const PENDING: VerifiedDomain = {
  id: '01900000-0000-7000-8000-00000000d001',
  domain: 'acme.test',
  state: 'pending',
  verified_at: null,
  verified_by_method: null,
  last_checked_at: '2026-11-20T10:00:00Z',
  last_outcome: 'not_found',
  failure_count: 0,
  record_name: '_supportx.acme.test',
  version: 1,
};
const VERIFIED: VerifiedDomain = {
  ...PENDING,
  id: '01900000-0000-7000-8000-00000000d002',
  domain: 'beta.test',
  state: 'verified',
  verified_at: '2026-11-20T11:00:00Z',
  verified_by_method: 'dns',
  last_outcome: 'found',
  record_name: '_supportx.beta.test',
};

describe('Sign-in and security › Verified domains', () => {
  it('lists domains in words and shows a new record once', async () => {
    const fake = consoleApi({
      me: ADMIN,
      routes: {
        'GET /api/v1/identity/domains': { body: [PENDING, VERIFIED] },
        'POST /api/v1/identity/domains': {
          status: 201,
          body: {
            ...PENDING,
            id: '01900000-0000-7000-8000-00000000d003',
            domain: 'new.test',
            record_name: '_supportx.new.test',
            last_checked_at: null,
            last_outcome: null,
            record_value: 'supportx-verification=abc123',
          },
        },
      },
    });
    restore = fake.restore;
    window.history.pushState({}, '', '/admin/security');
    render(<App />);
    const card = await screen.findByTestId('domains-card');
    await waitFor(() => {
      expect(within(card).getByText('acme.test')).toBeDefined();
    });
    expect(card.textContent).toContain('Waiting for its record');
    expect(card.textContent).toContain('Verified');
    expect(card.textContent).toContain("The record wasn't found yet");
    expect(card.textContent).not.toMatch(/not_found|pending\b/);
    expect(within(card).queryByTestId('domain-check-beta.test')).toBeNull(); // verified
    fireEvent.change(within(card).getByTestId('domains-add-input'), {
      target: { value: 'new.test' },
    });
    fireEvent.click(within(card).getByTestId('domains-add'));
    const record = await screen.findByTestId('domain-record');
    expect(record.textContent).toContain('_supportx.new.test');
    expect(record.textContent).toContain('supportx-verification=abc123');
    expect(record.textContent).toContain('shown only now');
  });
});
