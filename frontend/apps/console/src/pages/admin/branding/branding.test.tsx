import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { BrandingSettings } from '@supportx/api-client';
import { fakeBranding, fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-017 (REQ-ADM-055, REQ-PRT-016): the branding screen, the brand on every screen, live.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const ADMIN = fakeSession({ roles: ['tenant_admin'] });

function settings(overrides: Partial<BrandingSettings> = {}): BrandingSettings {
  return {
    ...fakeBranding(),
    chosen_primary_colour: null,
    chosen_gradient: null,
    logo_file_id: null,
    logo_dark_file_id: null,
    icon_file_id: null,
    ...overrides,
  };
}

const PASSING = {
  passes: true,
  checks: [{ code: 'text_on_primary', ratio: 5.93, required: 4.5, passed: true }],
  suggested_primary: null,
  suggested_gradient: null,
};
const FAILING = {
  passes: false,
  checks: [{ code: 'text_on_primary', ratio: 3.32, required: 4.5, passed: false }],
  suggested_primary: '#1765b3',
  suggested_gradient: null,
};

beforeEach(() => {
  localStorage.clear();
  window.history.pushState({}, '', '/admin/branding');
});
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

describe('branding screen', () => {
  it('REQ-ADM-055 AC2: a faint colour is shown as failing, cannot be saved, and the nearest passing one is one click away', async () => {
    const fake = api({
      me: ADMIN,
      routes: {
        'GET /api/v1/organization/branding/settings': {
          body: settings(),
          headers: { ETag: '"0"' },
        },
        'POST /api/v1/organization/branding/check': ({ body }) => ({
          body:
            (body as { primary_colour: string | null }).primary_colour === '#1e90ff'
              ? FAILING
              : PASSING,
        }),
        'PUT /api/v1/organization/branding/settings': ({ body }) => ({
          body: settings({
            chosen_primary_colour: (body as { primary_colour: string }).primary_colour,
            primary_colour: (body as { primary_colour: string }).primary_colour,
            customised: true,
            version: 1,
          }),
        }),
      },
    });
    render(<App />);
    const input = await screen.findByTestId('branding-primary-input');
    fireEvent.change(input, { target: { value: '#1e90ff' } });
    const alert = await screen.findByTestId('branding-contrast-alert');
    expect(within(screen.getByTestId('branding-checks')).getByText('Too faint')).toBeTruthy();
    expect(screen.getByTestId('branding-save').hasAttribute('disabled')).toBe(true);
    fireEvent.click(within(alert).getByTestId('branding-use-suggested'));
    await waitFor(() => {
      expect(screen.queryByTestId('branding-contrast-alert')).toBeNull();
    });
    await waitFor(() => {
      expect(screen.getByTestId('branding-save').hasAttribute('disabled')).toBe(false);
    });
    fireEvent.click(screen.getByTestId('branding-save'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/organization/branding/settings')).toHaveLength(1);
    });
    const put = fake.find('PUT', '/api/v1/organization/branding/settings')[0];
    expect(put?.headers.get('If-Match')).toBe('"0"');
    expect((put?.body as { primary_colour: string }).primary_colour).toBe('#1765b3');
    expect(await screen.findByText('Branding saved. Every open screen shows it now.')).toBeTruthy();
  });

  it('texts are entered per language, English first, and previewed on every theme', async () => {
    const fake = api({
      me: ADMIN,
      routes: {
        'GET /api/v1/organization/branding/settings': { body: settings() },
        'POST /api/v1/organization/branding/check': { body: PASSING },
        'PUT /api/v1/organization/branding/settings': { body: settings({ version: 1 }) },
      },
    });
    render(<App />);
    fireEvent.change(await screen.findByTestId('branding-portal_name-en'), {
      target: { value: 'Acme Help' },
    });
    fireEvent.click(within(screen.getByTestId('branding-preview-surface')).getByText('Portal'));
    for (const mode of ['light', 'dark', 'high_contrast']) {
      expect(
        within(screen.getByTestId(`branding-preview-${mode}`)).getByText('Acme Help'),
      ).toBeTruthy();
    }
    fireEvent.click(screen.getByRole('tab', { name: 'العربية' }));
    fireEvent.change(screen.getByTestId('branding-portal_name-ar'), {
      target: { value: 'مساعدة أكمي' },
    });
    await waitFor(() => {
      expect(screen.getByTestId('branding-save').hasAttribute('disabled')).toBe(false);
    });
    fireEvent.click(screen.getByTestId('branding-save'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/organization/branding/settings')).toHaveLength(1);
    });
    const body = fake.find('PUT', '/api/v1/organization/branding/settings')[0]?.body as {
      portal_name: Record<string, string>;
    };
    expect(body.portal_name).toEqual({ en: 'Acme Help', ar: 'مساعدة أكمي' });
  });

  it('the tab is offered only to people who may manage branding', async () => {
    api({ me: fakeSession({ roles: ['technician'] }) });
    window.history.pushState({}, '', '/admin');
    render(<App />);
    await screen.findByTestId('user-name');
    expect(screen.queryByRole('tab', { name: 'Branding' })).toBeNull();
  });
});

describe('the brand on every screen', () => {
  it('REQ-ADM-055 AC1: a saved brand reaches the open console without a reload, favicon included', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    let brand = fakeBranding();
    const fake = api({
      me: fakeSession(),
      routes: { 'GET /api/v1/organization/branding': () => ({ body: brand }) },
    });
    const icon = document.createElement('link');
    icon.rel = 'icon';
    icon.href = '/favicon.ico';
    document.head.append(icon);
    window.history.pushState({}, '', '/');
    render(<App />);
    await screen.findByTestId('user-name');
    expect(screen.getAllByTestId('brand-logo-full')[0]?.getAttribute('src')).not.toContain(
      '/public/branding/',
    );
    brand = fakeBranding({
      customised: true,
      primary_colour: '#0b5394',
      product_name: { en: 'Acme Desk' },
      logos: {
        full: '/api/v1/public/branding/demo/logo.png?v=1',
        favicon: '/api/v1/public/branding/demo/favicon.ico?v=1',
      },
      version: 1,
    });
    const before = fake.find('GET', '/api/v1/organization/branding').length;
    act(() => {
      realtime.publish(':broadcast', { type: 'organization.branding_changed', ids: [] });
    });
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/organization/branding').length).toBeGreaterThan(before);
    });
    await waitFor(() => {
      expect(screen.getAllByTestId('brand-logo-full')[0]?.getAttribute('src')).toBe(
        '/api/v1/public/branding/demo/logo.png?v=1',
      );
    });
    expect(screen.getAllByTestId('brand-logo-full')[0]?.getAttribute('alt')).toBe('Acme Desk');
    expect(icon.getAttribute('href')).toBe('/api/v1/public/branding/demo/favicon.ico?v=1');
    icon.remove();
  });
});

describe('addresses', () => {
  const DOMAIN = {
    id: 'd1',
    host: 'help.acme.test',
    status: 'pending',
    check_url: 'http://help.acme.test/api/v1/public/domain-check/tok',
    verified_at: null,
    checked_at: null,
    failure_code: null,
    tls_mode: 'automatic',
    tls_status: 'waiting',
    certificate_not_after: null,
    version: 1,
  } as const;

  it('REQ-PRT-016 AC3: a custom domain is added, checked, and says why a check failed', async () => {
    let items: unknown[] = [];
    const fake = api({
      me: ADMIN,
      routes: {
        'GET /api/v1/organization/branding/settings': { body: settings() },
        'POST /api/v1/organization/branding/check': { body: PASSING },
        'GET /api/v1/organization/domains': () => ({
          body: { subdomain: 'demo.support.example', point_to: 'demo.support.example', items },
        }),
        'POST /api/v1/organization/domains': () => {
          items = [DOMAIN];
          return { status: 201, body: DOMAIN };
        },
        'POST /api/v1/organization/domains/d1/verify': () => {
          const failed = {
            ...DOMAIN,
            status: 'failed',
            failure_code: 'domain_wrong_answer',
            version: 2,
          };
          items = [failed];
          return { body: failed };
        },
      },
    });
    render(<App />);
    expect((await screen.findByTestId('domains-subdomain')).textContent).toContain(
      'demo.support.example',
    );
    fireEvent.change(screen.getByTestId('domains-host'), { target: { value: 'help.acme.test' } });
    fireEvent.click(screen.getByTestId('domains-add'));
    await screen.findByTestId('domain-help.acme.test');
    const add = fake.find('POST', '/api/v1/organization/domains')[0];
    expect(add?.headers.get('Idempotency-Key')).toBeTruthy();
    expect(screen.getByText('Not checked yet')).toBeTruthy();
    fireEvent.click(screen.getByTestId('domain-verify-help.acme.test'));
    expect(
      (
        await screen.findAllByText(
          'The domain does not point to this SupportX yet: check its DNS record.',
        )
      ).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText('Check failed')).toBeTruthy();
  });
});
