import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { SsoPolicy } from '@supportx/api-client';
import { fakeSession, problem } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-057 S1b: Admin › Sign-in and security › Single sign-on required (REQ-SEC-009, 026).

let restore: () => void = () => undefined;
const ADMIN = fakeSession({ roles: ['tenant_admin'] });
const ME = '01900000-0000-7000-8000-000000000101'; // fakeSession's user
const OTHER = '01900000-0000-7000-8000-000000000202';
const NO_MFA = '01900000-0000-7000-8000-000000000303';
const POLICY: SsoPolicy = {
  sso_required: 'off',
  sso_also_require_mfa: false,
  break_glass_admins: 0,
  admins: [
    {
      user_id: ME,
      display_name: 'Ayesha Admin',
      mfa_enrolled: true,
      break_glass: false,
      break_glass_ip_exempt: false,
      version: 3,
    },
    {
      user_id: OTHER,
      display_name: 'Omar Other',
      mfa_enrolled: true,
      break_glass: false,
      break_glass_ip_exempt: false,
      version: 5,
    },
    {
      user_id: NO_MFA,
      display_name: 'Nadia NoCode',
      mfa_enrolled: false,
      break_glass: false,
      break_glass_ip_exempt: false,
      version: 1,
    },
  ],
  version: 0,
};

function api(extra: Record<string, unknown> = {}) {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/identity/settings': { body: {} },
      'GET /api/v1/identity/sso': { body: { items: [] } },
      'GET /api/v1/identity/invitations': { body: { items: [] } },
      'GET /api/v1/identity/sso-policy': { body: POLICY },
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

describe('Single sign-on required', () => {
  it('REQ-SEC-009 AC2: requiring it without an emergency administrator is refused in words', async () => {
    const fake = api({
      'PUT /api/v1/identity/sso-policy': {
        status: 409,
        body: problem(409, 'sso_required_needs_break_glass'),
      },
    });
    render(<App />);
    const modes = await screen.findByTestId('security-sso-required');
    const card = screen.getByTestId('security-sso-policy');
    fireEvent.click(within(modes).getByText('Everyone'));
    expect(screen.getByTestId('security-sso-required-effect')).toBeTruthy();
    fireEvent.click(screen.getByTestId('security-sso-policy-save'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/identity/sso-policy')).toHaveLength(1);
    });
    const [sent] = fake.find('PUT', '/api/v1/identity/sso-policy');
    expect(sent?.body).toEqual({ sso_required: 'everyone', sso_also_require_mfa: false });
    expect(sent?.headers.get('If-Match')).toBe('"0"');
    expect(
      await within(card).findByText(/emergency administrator/i, { selector: '[role="alert"] *' }),
    ).toBeTruthy();
    expect(card.textContent).not.toContain('sso_required_needs_break_glass');
  });

  it('names another admin with two-step sign-in after asking; never yourself or one without it', async () => {
    const fake = api({
      [`PUT /api/v1/identity/break-glass/${OTHER}`]: {
        body: { user_id: OTHER, break_glass: true, break_glass_ip_exempt: false, version: 6 },
      },
    });
    render(<App />);
    const mine = await screen.findByTestId(`security-break-glass-${ME}`);
    expect(mine.hasAttribute('disabled') || mine.getAttribute('aria-disabled') === 'true').toBe(
      true,
    );
    expect(screen.getByText('Another administrator must name you.')).toBeTruthy();
    expect(screen.getByText('Needs two-step sign-in first.')).toBeTruthy();
    // The IP exemption waits until the person is an emergency administrator.
    expect(screen.getByTestId(`security-break-glass-ip-${OTHER}`).hasAttribute('disabled')).toBe(
      true,
    );
    fireEvent.click(screen.getByTestId(`security-break-glass-${OTHER}`));
    fireEvent.click(await screen.findByText('Make emergency administrator'));
    await waitFor(() => {
      expect(fake.find('PUT', `/api/v1/identity/break-glass/${OTHER}`)).toHaveLength(1);
    });
    const [sent] = fake.find('PUT', `/api/v1/identity/break-glass/${OTHER}`);
    expect(sent?.body).toEqual({ break_glass: true, break_glass_ip_exempt: false });
    expect(sent?.headers.get('If-Match')).toBe('"5"');
  });
});
