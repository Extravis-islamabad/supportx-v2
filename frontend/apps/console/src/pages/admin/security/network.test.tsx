import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { NetworkRules } from '@supportx/api-client';
import { fakeSession, problem } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-057 S1a: Admin › Sign-in and security › IP allow-lists (REQ-SEC-034).

let restore: () => void = () => undefined;
const ADMIN = fakeSession({ roles: ['tenant_admin'] });
const OPEN: NetworkRules = {
  console_ip_allow: [],
  portal_ip_allow: [],
  api_ip_allow: [],
  your_address: '203.0.113.7',
  version: 0,
};

function api(extra: Record<string, unknown> = {}) {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/identity/settings': { body: {} },
      'GET /api/v1/identity/sso': { body: { items: [] } },
      'GET /api/v1/identity/invitations': { body: { items: [] } },
      'GET /api/v1/identity/network-rules': { body: OPEN },
      ...extra,
    },
  });
  restore = fake.restore;
  return fake;
}

beforeEach(() => {
  window.history.pushState({}, '', '/admin/security');
});
afterEach(() => {
  restore();
});

describe('IP allow-lists', () => {
  it('REQ-SEC-034: shows your address, adds it, and saves the three lists with If-Match', async () => {
    const fake = api({
      'PUT /api/v1/identity/network-rules': {
        body: { ...OPEN, console_ip_allow: ['203.0.113.7/32', '10.20.0.0/16'], version: 1 },
      },
    });
    render(<App />);
    expect((await screen.findByTestId('security-network-here')).textContent).toContain(
      '203.0.113.7',
    );
    fireEvent.click(screen.getByTestId('security-console_ip_allow-add-here'));
    const box = screen.getByTestId('security-console_ip_allow');
    fireEvent.change(box, { target: { value: '203.0.113.7\n10.20.0.0/16' } });
    expect(screen.getByText('Only from 2 addresses or ranges.')).toBeTruthy();
    fireEvent.click(screen.getByTestId('security-network-save'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/identity/network-rules')).toHaveLength(1);
    });
    const [sent] = fake.find('PUT', '/api/v1/identity/network-rules');
    expect(sent?.body).toEqual({
      console_ip_allow: ['203.0.113.7', '10.20.0.0/16'],
      portal_ip_allow: [],
      api_ip_allow: [],
    });
    expect(sent?.headers.get('If-Match')).toBe('"0"');
    expect(await screen.findByText('IP allow-lists saved.')).toBeTruthy();
  });

  it('REQ-SEC-034 AC2: a list that would shut you out is refused at that list, in words', async () => {
    api({
      'PUT /api/v1/identity/network-rules': {
        status: 422,
        body: problem(422, 'validation_failed', {
          errors: [
            {
              field: 'console_ip_allow',
              code: 'ip_allow_locks_you_out',
              message_key: 'errors.field.ip_allow_locks_you_out',
              params: { address: '203.0.113.7' },
            },
          ],
        }),
      },
    });
    render(<App />);
    fireEvent.change(await screen.findByTestId('security-console_ip_allow'), {
      target: { value: '10.20.0.0/16' },
    });
    fireEvent.click(screen.getByTestId('security-network-save'));
    expect(
      await screen.findByText(
        'This list would shut you out: your address 203.0.113.7 is not in it. Add it, or a range that holds it.',
      ),
    ).toBeTruthy();
  });

  it('more entries than the server takes are refused while typing', async () => {
    api();
    render(<App />);
    const many = Array.from({ length: 51 }, (_, i) => `10.0.${String(i)}.0/24`).join('\n');
    fireEvent.change(await screen.findByTestId('security-portal_ip_allow'), {
      target: { value: many },
    });
    expect(screen.getByText('Use at most 50 entries.')).toBeTruthy();
    expect(screen.getByTestId('security-network-save').hasAttribute('disabled')).toBe(true);
  });
});
