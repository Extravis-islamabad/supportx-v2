import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { BrandingSettings } from '@supportx/api-client';
import { fakeBranding, fakeSession, problem } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';
import { SUPPORTX_LOGOS, TAG_TONES } from '@supportx/ui';

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
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  Reflect.deleteProperty(HTMLImageElement.prototype, 'decode');
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

// ---- WP-017-FIX: the QA bugs of ~/Desktop/qa-wp017/QA-REPORT.md, one test (or more) per ID ----

const PNG = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13];

/** Uploads through XMLHttpRequest (uploadFile): each answers with a stored file, scanning. */
function fakeUploads() {
  const sent: string[] = [];
  class FakeRequest {
    status = 0;
    responseText = '';
    upload: { onprogress: unknown } = { onprogress: null };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onabort: (() => void) | null = null;
    private url = '';
    open(_method: string, url: string) {
      this.url = url;
    }
    setRequestHeader() {
      return undefined;
    }
    getResponseHeader() {
      return null;
    }
    abort() {
      return undefined;
    }
    send() {
      const name = new URL(this.url, 'http://console.test').searchParams.get('name') ?? '';
      sent.push(name);
      setTimeout(() => {
        this.status = 201;
        this.responseText = JSON.stringify({ id: `f-${name}`, name, state: 'scanning' });
        this.onload?.();
      }, 0);
    }
  }
  vi.stubGlobal('XMLHttpRequest', FakeRequest);
  return sent;
}

/** What the browser decodes from a chosen image (jsdom decodes nothing by itself). */
function browserDecodes(size: { width: number; height: number } | 'nothing') {
  URL.createObjectURL = vi.fn(() => 'blob:chosen');
  URL.revokeObjectURL = vi.fn();
  // jsdom has no HTMLImageElement.decode: defined here, removed after each test.
  Object.defineProperty(HTMLImageElement.prototype, 'decode', {
    configurable: true,
    writable: true,
    value: () =>
      size === 'nothing' ? Promise.reject(new Error('EncodingError')) : Promise.resolve(),
  });
  vi.spyOn(HTMLImageElement.prototype, 'naturalWidth', 'get').mockReturnValue(
    size === 'nothing' ? 0 : size.width,
  );
  vi.spyOn(HTMLImageElement.prototype, 'naturalHeight', 'get').mockReturnValue(
    size === 'nothing' ? 0 : size.height,
  );
}

function choose(field: string, file: File) {
  fireEvent.change(screen.getByTestId(`branding-${field}-input`), { target: { files: [file] } });
}

const LOGO_SAVED = settings({
  logo_file_id: 'f-saved-logo',
  logos: { ...fakeBranding().logos, full: '/api/v1/public/branding/t/logo.png?v=1' },
});

describe('WP-017-FIX', () => {
  it('BUG-01: the preview draws exactly the colours that will be saved (a primary alone colours the gradient too)', async () => {
    api({
      me: ADMIN,
      routes: {
        'GET /api/v1/organization/branding/settings': {
          body: settings({
            chosen_primary_colour: '#7a1f1f',
            primary_colour: '#7a1f1f',
            gradient: ['#7a1f1f', '#7a1f1f'],
          }),
        },
        'POST /api/v1/organization/branding/check': { body: PASSING },
      },
    });
    render(<App />);
    fireEvent.change(await screen.findByTestId('branding-primary-input'), {
      target: { value: '#0b5394' },
    });
    const band = () =>
      within(screen.getByTestId('branding-preview-light')).getByTestId('branding-preview-band');
    fireEvent.click(within(screen.getByTestId('branding-preview-surface')).getByText('Portal'));
    // No own gradient: the saved brand runs from the primary to the primary (server rule).
    await waitFor(() => {
      expect(band().dataset.gradient).toBe('#0b5394,#0b5394');
    });
    // Back to the default: the default colours, not the ones saved before.
    fireEvent.click(screen.getByText('Use the default colours'));
    await waitFor(() => {
      expect(band().dataset.gradient).toBe('#6060de,#951ab6');
    });
  });

  it('BUG-02: a domain that is not a host name is refused at the field as it is typed', async () => {
    const fake = api({
      me: ADMIN,
      routes: {
        'GET /api/v1/organization/branding/settings': { body: settings() },
        'POST /api/v1/organization/branding/check': { body: PASSING },
        'GET /api/v1/organization/domains': {
          body: { subdomain: 'demo.support.example', point_to: 'demo.support.example', items: [] },
        },
      },
    });
    render(<App />);
    const host = await screen.findByTestId('domains-host');
    for (const value of ['10.0.0.1', 'https://help.acme.test', 'help', 'help.acme.test/x']) {
      fireEvent.change(host, { target: { value } });
      const field = screen.getByTestId('domains-host-field');
      expect(within(field).getByRole('alert').textContent).toBe(
        'Enter a domain name such as help.example.com.',
      );
      expect(screen.getByTestId('domains-add').hasAttribute('disabled')).toBe(true);
    }
    fireEvent.change(host, { target: { value: 'help.acme.test' } });
    expect(within(screen.getByTestId('domains-host-field')).queryByRole('alert')).toBeNull();
    expect(fake.find('POST', '/api/v1/organization/domains')).toHaveLength(0);
  });

  it('BUG-02: a domain the server refuses (reserved, already used) says why at the field', async () => {
    api({
      me: ADMIN,
      routes: {
        'GET /api/v1/organization/branding/settings': { body: settings() },
        'POST /api/v1/organization/branding/check': { body: PASSING },
        'GET /api/v1/organization/domains': {
          body: { subdomain: 'demo.support.example', point_to: 'demo.support.example', items: [] },
        },
        'POST /api/v1/organization/domains': ({ body }) =>
          (body as { host: string }).host === 'qa.support.example'
            ? {
                status: 422,
                body: problem(422, 'validation_failed', {
                  errors: [
                    {
                      field: 'host',
                      code: 'domain_reserved',
                      message_key: 'errors.field.domain_reserved',
                      params: {},
                    },
                  ],
                }),
              }
            : { status: 409, body: problem(409, 'domain_taken') },
      },
    });
    render(<App />);
    const host = await screen.findByTestId('domains-host');
    fireEvent.change(host, { target: { value: 'qa.support.example' } });
    fireEvent.click(screen.getByTestId('domains-add'));
    expect(
      (await within(screen.getByTestId('domains-host-field')).findByRole('alert')).textContent,
    ).toBe("Addresses under this installation's own domain are given automatically.");
    fireEvent.change(host, { target: { value: 'HELP.acme.test' } });
    expect(within(screen.getByTestId('domains-host-field')).queryByRole('alert')).toBeNull();
    fireEvent.click(screen.getByTestId('domains-add'));
    expect(
      (await within(screen.getByTestId('domains-host-field')).findByRole('alert')).textContent,
    ).toBe('This domain is already used.');
  });

  it('BUG-02: a certificate is checked as it is pasted, and a refused one says why in the dialog', async () => {
    const DOMAIN = {
      id: 'd1',
      host: 'help.acme.test',
      status: 'verified',
      check_url: 'http://help.acme.test/api/v1/public/domain-check/tok',
      verified_at: '2026-10-27T10:00:00Z',
      checked_at: '2026-10-27T10:00:00Z',
      failure_code: null,
      tls_mode: 'uploaded',
      tls_status: 'not_managed',
      certificate_not_after: null,
      version: 2,
    };
    api({
      me: ADMIN,
      routes: {
        'GET /api/v1/organization/branding/settings': { body: settings() },
        'POST /api/v1/organization/branding/check': { body: PASSING },
        'GET /api/v1/organization/domains': {
          body: { subdomain: null, point_to: 'support.example', items: [DOMAIN] },
        },
        'PUT /api/v1/organization/domains/d1/certificate': {
          status: 422,
          body: problem(422, 'validation_failed', {
            errors: [
              {
                field: 'certificate',
                code: 'certificate_wrong_host',
                message_key: 'errors.field.certificate_wrong_host',
                params: {},
              },
            ],
          }),
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('domain-certificate-help.acme.test'));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByTestId('domain-certificate'), {
      target: { value: 'not a certificate' },
    });
    fireEvent.change(within(dialog).getByTestId('domain-private-key'), {
      target: { value: 'not a key' },
    });
    expect(
      within(within(dialog).getByTestId('domain-certificate-field')).getByRole('alert').textContent,
    ).toBe('The certificate cannot be read: paste it in PEM format.');
    expect(
      within(within(dialog).getByTestId('domain-private-key-field')).getByRole('alert').textContent,
    ).toBe('The private key cannot be read: paste it unencrypted in PEM format.');
    const ok = within(dialog).getByRole('button', { name: 'Use this certificate' });
    expect(ok.hasAttribute('disabled')).toBe(true);
    fireEvent.change(within(dialog).getByTestId('domain-certificate'), {
      target: { value: '-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----' },
    });
    fireEvent.change(within(dialog).getByTestId('domain-private-key'), {
      target: { value: '-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----' },
    });
    await waitFor(() => {
      expect(ok.hasAttribute('disabled')).toBe(false);
    });
    fireEvent.click(ok);
    expect(
      (await within(within(dialog).getByTestId('domain-certificate-field')).findByRole('alert'))
        .textContent,
    ).toBe('The certificate does not name this domain.');
    expect(screen.getByRole('dialog')).toBeTruthy(); // still open, to correct it
  });

  it('BUG-03: a colour that is not #rrggbb is flagged at once and cannot be saved', async () => {
    const fake = api({
      me: ADMIN,
      routes: {
        'GET /api/v1/organization/branding/settings': { body: settings() },
        'POST /api/v1/organization/branding/check': { body: PASSING },
      },
    });
    render(<App />);
    const input = await screen.findByTestId('branding-primary-input');
    fireEvent.change(input, { target: { value: '#0b5394' } });
    await screen.findByTestId('branding-checks');
    fireEvent.change(input, { target: { value: 'blue' } });
    expect(
      within(screen.getByTestId('branding-primary-field')).getByRole('alert').textContent,
    ).toBe('Choose a colour such as #1677ff.');
    expect(screen.getByTestId('branding-save').hasAttribute('disabled')).toBe(true);
    expect(screen.queryByTestId('branding-checks')).toBeNull(); // no stale result for another colour
    await new Promise((resolve) => setTimeout(resolve, 600));
    const sent = fake
      .find('POST', '/api/v1/organization/branding/check')
      .map((call) => (call.body as { primary_colour: string | null }).primary_colour);
    expect(sent).not.toContain('blue');
    // #rgb is a colour too (the server accepts it): saved as #rrggbb.
    fireEvent.change(input, { target: { value: '#0AF' } });
    expect(within(screen.getByTestId('branding-primary-field')).queryByRole('alert')).toBeNull();
  });

  it('BUG-03: a save the server refuses says why at the field', async () => {
    api({
      me: ADMIN,
      routes: {
        'GET /api/v1/organization/branding/settings': { body: settings() },
        'POST /api/v1/organization/branding/check': { body: PASSING },
        'PUT /api/v1/organization/branding/settings': {
          status: 422,
          body: problem(422, 'validation_failed', {
            errors: [
              {
                field: 'portal_name.en',
                code: 'english_text_required',
                message_key: 'errors.field.english_text_required',
                params: {},
              },
            ],
          }),
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'العربية' }));
    fireEvent.change(screen.getByTestId('branding-portal_name-ar'), {
      target: { value: 'مساعدة' },
    });
    await waitFor(() => {
      expect(screen.getByTestId('branding-save').hasAttribute('disabled')).toBe(false);
    });
    fireEvent.click(screen.getByTestId('branding-save'));
    fireEvent.click(await screen.findByRole('tab', { name: 'English' }));
    expect(
      (await within(screen.getByTestId('branding-portal_name-en-field')).findByRole('alert'))
        .textContent,
    ).toBe('Add the English text: it is shown wherever no translation exists.');
  });

  it('BUG-04: the contrast checks use the readable tone tags, passed and failed', async () => {
    api({
      me: ADMIN,
      routes: {
        'GET /api/v1/organization/branding/settings': { body: settings() },
        'POST /api/v1/organization/branding/check': {
          body: {
            ...FAILING,
            checks: [PASSING.checks[0], { ...FAILING.checks[0], code: 'links_on_white' }],
          },
        },
      },
    });
    render(<App />);
    fireEvent.change(await screen.findByTestId('branding-primary-input'), {
      target: { value: '#1e90ff' },
    });
    const checks = await screen.findByTestId('branding-checks');
    const passed = within(checks).getByText('Readable');
    const failed = within(checks).getByText('Too faint');
    expect(passed.closest('[data-tone]')?.getAttribute('data-tone')).toBe('success');
    expect(failed.closest('[data-tone]')?.getAttribute('data-tone')).toBe('error');
    expect(passed.closest<HTMLElement>('[data-tone]')?.style.color).toBe(
      hexToRgb(TAG_TONES.light.success.color),
    );
  });

  it('BUG-05: the empty list of domains is readable text (secondary, not the faint empty style)', async () => {
    localStorage.setItem('supportx.theme_mode', 'dark');
    api({
      me: ADMIN,
      routes: {
        'GET /api/v1/organization/branding/settings': { body: settings() },
        'POST /api/v1/organization/branding/check': { body: PASSING },
        'GET /api/v1/organization/domains': {
          body: { subdomain: null, point_to: 'support.example', items: [] },
        },
      },
    });
    render(<App />);
    const empty = await within(await screen.findByTestId('branding-domains')).findByText(
      'No custom domains yet.',
    );
    expect(empty.closest('.ant-typography-secondary')).not.toBeNull();
    expect(empty.closest('.ant-empty-description')).toBeNull();
  });

  it('BUG-06: an image card without an upload shows the SupportX default image it stands for', async () => {
    api({
      me: ADMIN,
      routes: {
        'GET /api/v1/organization/branding/settings': { body: settings() },
        'POST /api/v1/organization/branding/check': { body: PASSING },
      },
    });
    render(<App />);
    const dark = await screen.findByTestId('branding-logo_dark_file_id');
    const image = within(dark).getByRole('img', { name: 'SupportX default' });
    expect(image.getAttribute('src')).toBe(SUPPORTX_LOGOS.fullOnDark);
    const light = within(screen.getByTestId('branding-logo_file_id')).getByRole('img', {
      name: 'SupportX default',
    });
    expect(light.getAttribute('src')).toBe(SUPPORTX_LOGOS.full);
  });

  it('BUG-07: removing the logo while the icon is still being checked leaves Save usable', async () => {
    const sent = fakeUploads();
    browserDecodes({ width: 96, height: 96 });
    const fake = api({
      me: ADMIN,
      routes: {
        'GET /api/v1/organization/branding/settings': { body: LOGO_SAVED },
        'POST /api/v1/organization/branding/check': { body: PASSING },
        'GET /api/v1/files/f-icon.png': { body: { id: 'f-icon.png', state: 'scanning' } },
        'PUT /api/v1/organization/branding/settings': { body: settings({ version: 1 }) },
      },
    });
    render(<App />);
    await screen.findByTestId('branding-logo_file_id');
    choose('icon_file_id', new File([new Uint8Array(PNG)], 'icon.png', { type: 'image/png' }));
    await waitFor(() => {
      expect(sent).toEqual(['icon.png']);
    });
    expect(await screen.findByText('Checking the file for malware…')).toBeTruthy();
    expect(screen.getByTestId('branding-save').hasAttribute('disabled')).toBe(true);
    fireEvent.click(screen.getByTestId('branding-logo_file_id-remove'));
    await waitFor(() => {
      expect(screen.getByTestId('branding-save').hasAttribute('disabled')).toBe(false);
    });
    fireEvent.click(screen.getByTestId('branding-save'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/organization/branding/settings')).toHaveLength(1);
    });
    expect(fake.find('PUT', '/api/v1/organization/branding/settings')[0]?.body).toMatchObject({
      logo_file_id: null,
      logo_dark_file_id: null,
      icon_file_id: null,
    });
  });

  it('BUG-09: an SVG, a file that is no image, a broken image and a too large one are refused on selection, never uploaded', async () => {
    const sent = fakeUploads();
    api({
      me: ADMIN,
      routes: {
        'GET /api/v1/organization/branding/settings': { body: settings() },
        'POST /api/v1/organization/branding/check': { body: PASSING },
      },
    });
    render(<App />);
    const card = await screen.findByTestId('branding-logo_file_id');
    const refusal = async () => (await within(card).findByRole('alert')).textContent;

    browserDecodes({ width: 400, height: 100 });
    choose(
      'logo_file_id',
      new File(['<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>'], 'logo.png', {
        type: 'image/png',
      }),
    );
    expect(await refusal()).toBe(
      'SVG images are not accepted: they can contain scripts. Use a PNG, JPEG, WebP or ICO file.',
    );
    choose('logo_file_id', new File(['%PDF-1.7 not an image'], 'logo.png', { type: 'image/png' }));
    await waitFor(async () => {
      expect(await refusal()).toBe('This image cannot be read. Use a PNG, JPEG, WebP or ICO file.');
    });
    browserDecodes('nothing');
    choose('logo_file_id', new File([new Uint8Array(PNG)], 'broken.png', { type: 'image/png' }));
    await waitFor(async () => {
      expect(await refusal()).toBe('This image cannot be read. Use a PNG, JPEG, WebP or ICO file.');
    });
    browserDecodes({ width: 10, height: 10 });
    choose('logo_file_id', new File([new Uint8Array(PNG)], 'tiny.png', { type: 'image/png' }));
    await waitFor(async () => {
      expect(await refusal()).toBe('This image is too small: at least 16 pixels on each side.');
    });
    browserDecodes({ width: 400, height: 100 });
    const big = new Uint8Array(5 * 1024 * 1024 + 1);
    big.set(PNG);
    choose('logo_file_id', new File([big], 'big.png', { type: 'image/png' }));
    await waitFor(async () => {
      expect(await refusal()).toBe('This image is too large: at most 5 MB and 25 megapixels.');
    });
    expect(sent).toEqual([]); // nothing refused was uploaded
    expect(screen.getByTestId('branding-save').hasAttribute('disabled')).toBe(false);
    // A real one is taken.
    choose('logo_file_id', new File([new Uint8Array(PNG)], 'logo.png', { type: 'image/png' }));
    await waitFor(() => {
      expect(sent).toEqual(['logo.png']);
    });
    expect(within(card).queryByRole('alert')).toBeNull();
  });
});

function hexToRgb(hex: string): string {
  const [r, g, b] = [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16));
  return `rgb(${String(r)}, ${String(g)}, ${String(b)})`;
}
