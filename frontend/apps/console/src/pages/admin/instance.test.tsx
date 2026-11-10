import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { TenantSettings } from '@supportx/api-client';
import { fakeSession, type FakeRoute } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-042 (REQ-ADM-049, 050, 052): Admin › Instance settings.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const ADMIN = fakeSession({ roles: ['tenant_admin', 'technician'] });
const SAVED: TenantSettings = {
  time_zone: 'Asia/Karachi',
  week_start: 'monday',
  date_format: 'dd/mm/yyyy',
  time_format: '24h',
  country: 'PK',
  fiscal_year_start_month: 7,
  contact_email: null,
  contact_phone: null,
  base_currency: 'PKR',
  languages: ['en', 'ar', 'ur'],
  default_language: 'en',
  version: 3,
};

function api(routes: Record<string, FakeRoute> = {}) {
  const fake = consoleApi({
    me: ADMIN,
    routes: { 'GET /api/v1/organization/settings': { body: SAVED }, ...routes },
  });
  restore = fake.restore;
  return fake;
}

describe('Admin › Instance settings', () => {
  it('saves with If-Match, and a currency change asks first', async () => {
    window.history.pushState({}, '', '/admin/instance');
    const fake = api({
      'PATCH /api/v1/organization/settings': { body: { ...SAVED, version: 4 } },
    });
    render(<App />);
    const page = await screen.findByTestId('instance');
    // Template E: the shell's settings header names the page.
    expect(screen.getByTestId('admin-page-header').textContent).toContain('Instance settings');
    // Choose another currency, then save: the confirmation names both.
    const currency = within(page).getByTestId('instance-currency');
    fireEvent.mouseDown(currency.querySelector('input') ?? currency);
    fireEvent.change(currency.querySelector('input') ?? currency, { target: { value: 'AED' } });
    fireEvent.click(
      await screen.findByText(/\(AED\)$/, { selector: '.ant-select-item-option-content' }),
    );
    fireEvent.click(await screen.findByTestId('settings-save')); // template E's save bar
    const dialog = await screen.findByRole('dialog', { name: /Change the base currency from/ });
    expect(fake.find('PATCH', '/api/v1/organization/settings')).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Change currency' }));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/organization/settings')).toHaveLength(1);
    });
    const [call] = fake.find('PATCH', '/api/v1/organization/settings');
    expect(call?.headers.get('If-Match')).toBe('"3"');
    expect(call?.body).toMatchObject({ base_currency: 'AED', confirm_currency: true });
  });

  it("QA10-P3-12: a wrong e-mail gets the app's own field error, and nothing is saved", async () => {
    window.history.pushState({}, '', '/admin/instance');
    const fake = api({
      'PATCH /api/v1/organization/settings': { body: { ...SAVED, version: 4 } },
    });
    render(<App />);
    const email = await screen.findByTestId('instance-contact-email');
    expect(email.closest('form')?.noValidate).toBe(true); // never the browser's bubble
    fireEvent.change(email, { target: { value: 'not-an-email' } });
    fireEvent.blur(email);
    expect(await screen.findByText('Enter an e-mail address like name@example.com.')).toBeTruthy();
    fireEvent.click(await screen.findByTestId('settings-save'));
    await waitFor(() => {
      expect(screen.getAllByText('Enter an e-mail address like name@example.com.').length).toBe(1);
    });
    expect(fake.find('PATCH', '/api/v1/organization/settings')).toHaveLength(0);
  });
});
