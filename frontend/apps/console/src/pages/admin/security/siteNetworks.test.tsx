import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { SiteNetworks } from '@supportx/api-client';
import { fakeSession, problem } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-057 S2b-1 (D-170 item 2): Admin › Sign-in and security › Address ranges by site.

let restore: () => void = () => undefined;
const ADMIN = fakeSession({ roles: ['tenant_admin'] });
const HQ = '00000000-0000-7000-8000-0000000000a1';
const LAB = '00000000-0000-7000-8000-0000000000a2';
const SAVED: SiteNetworks = {
  entries: [{ network: '10.1.0.0/16', site_id: HQ }],
  version: 3,
  geoip_built_at: '2026-10-01T00:00:00Z',
};

function api(extra: Record<string, unknown> = {}) {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/identity/settings': { body: {} },
      'GET /api/v1/identity/sso': { body: { items: [] } },
      'GET /api/v1/identity/invitations': { body: { items: [] } },
      'GET /api/v1/identity/site-networks': { body: SAVED },
      'GET /api/v1/organization/sites': {
        body: [
          { id: HQ, name: 'Islamabad HQ', disabled: false },
          { id: LAB, name: 'Lahore lab', disabled: false },
        ],
      },
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

describe('Address ranges by site', () => {
  it('lists the saved ranges, adds one and saves the whole list with If-Match', async () => {
    const fake = api({
      'PUT /api/v1/identity/site-networks': {
        body: {
          ...SAVED,
          entries: [
            { network: '10.1.7.0/24', site_id: LAB },
            { network: '10.1.0.0/16', site_id: HQ },
          ],
          version: 4,
        },
      },
    });
    render(<App />);
    const card = await screen.findByTestId('security-site-networks');
    expect(
      (await within(card).findByTestId('security-site-network-0-range')).getAttribute('value'),
    ).toBe('10.1.0.0/16');
    expect(within(card).getByTestId('security-geoip-date').textContent).toContain(
      'Place database built',
    );
    fireEvent.click(within(card).getByTestId('security-site-networks-add'));
    fireEvent.change(within(card).getByTestId('security-site-network-1-range'), {
      target: { value: '10.1.7.0/24' },
    });
    // Ant Design's Select: open it and pick the option by its name.
    fireEvent.mouseDown(
      within(within(card).getByTestId('security-site-network-1-site')).getByRole('combobox'),
    );
    fireEvent.click(await screen.findByTitle('Lahore lab'));
    fireEvent.click(within(card).getByTestId('security-site-networks-save'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/identity/site-networks')).toHaveLength(1);
    });
    const [sent] = fake.find('PUT', '/api/v1/identity/site-networks');
    expect(sent?.body).toEqual({
      entries: [
        { network: '10.1.0.0/16', site_id: HQ },
        { network: '10.1.7.0/24', site_id: LAB },
      ],
    });
    expect(sent?.headers.get('If-Match')).toBe('"3"');
    expect(await screen.findByText('Address ranges saved.')).toBeTruthy();
  });

  it('a wrong range is refused at its row, in words', async () => {
    api({
      'PUT /api/v1/identity/site-networks': {
        status: 422,
        body: problem(422, 'validation_failed', {
          errors: [
            {
              field: 'entries.0',
              code: 'site_network_invalid',
              message_key: 'errors.field.site_network_invalid',
              params: { entry: '10.1.2.3/16' },
            },
          ],
        }),
      },
    });
    render(<App />);
    const card = await screen.findByTestId('security-site-networks');
    // Straight away: the rows keep their identity while the rest of the page loads.
    fireEvent.change(await within(card).findByTestId('security-site-network-0-range'), {
      target: { value: '10.1.2.3/16' },
    });
    fireEvent.click(within(card).getByTestId('security-site-networks-save'));
    expect(
      await within(card).findByText(
        'Enter a range such as 10.1.0.0/16 (with the host part zero), or one address.',
      ),
    ).toBeTruthy();
  });

  it('says when no place database is installed', async () => {
    api({ 'GET /api/v1/identity/site-networks': { body: { ...SAVED, geoip_built_at: null } } });
    render(<App />);
    expect((await screen.findByTestId('security-geoip-date')).textContent).toBe(
      'No place database is installed: sign-ins outside the mapped ranges show no city.',
    );
  });
});
