import { screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeApi, fakeSession } from '@supportx/api-client/testing';

import { SessionGate } from './SessionGate';
import { renderUi } from './test/render';
import { LOCALE_STORAGE_KEY, storedLocale } from './themeMode';

// QA 2026-11-12: V-01 (the loading screen white in dark, a grey box, English in Arabic) and
// V-02 (a white scrollbar strip on every dark screen).

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  document.documentElement.style.colorScheme = '';
  document.body.style.background = '';
});

describe('the page takes the theme', () => {
  it('V-02: dark sets color-scheme dark, so the browser draws dark scrollbars', () => {
    renderUi(<p>page</p>, { mode: 'dark' });
    expect(document.documentElement.style.colorScheme).toBe('dark');
    // The theme's layout background (#121317), not the browser's white.
    expect(document.body.style.background).toMatch(/rgb\(18, 19, 23\)|#121317/i);
  });

  it('V-02: light and high contrast keep light scrollbars and their own background', () => {
    renderUi(<p>page</p>, { mode: 'light' });
    expect(document.documentElement.style.colorScheme).toBe('light');
    expect(document.body.style.background).toMatch(/rgb\(244, 245, 247\)|#f4f5f7/i);
    renderUi(<p>page</p>, { mode: 'high_contrast' });
    expect(document.documentElement.style.colorScheme).toBe('light');
  });
});

describe('the loading screen', () => {
  it('V-01: the logo, a spinner and the words, in the language, with no grey box', async () => {
    const fake = fakeApi({ 'GET /api/v1/auth/me': () => new Promise(() => undefined) });
    restore = fake.restore;
    renderUi(<SessionGate app="console">{() => <p>signed in</p>}</SessionGate>, {
      locale: 'ar',
      mode: 'dark',
    });
    const loading = await screen.findByTestId('session-loading');
    expect(loading.getAttribute('role')).toBe('status');
    expect(loading.textContent).not.toMatch(/Checking your session/);
    expect(loading.textContent.trim()).not.toBe('');
    // A Spin round a placeholder draws a blurred grey box; a bare spinner draws none.
    expect(loading.querySelector('.ant-spin-nested-loading')).toBeNull();
    expect(loading.querySelector('.ant-spin')).not.toBeNull();
  });

  it("V-01: remembers the person's language for the next visit's loading screen", async () => {
    window.localStorage.removeItem(LOCALE_STORAGE_KEY);
    const fake = fakeApi({ 'GET /api/v1/auth/me': { body: fakeSession({ locale: 'ur' }) } });
    restore = fake.restore;
    renderUi(<SessionGate app="console">{() => <p>signed in</p>}</SessionGate>);
    expect(await screen.findByText('signed in')).toBeDefined();
    await waitFor(() => {
      expect(storedLocale()).toBe('ur');
    });
  });

  it('V-01: an unknown stored language is ignored', () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, 'xx');
    expect(storedLocale()).toBeNull();
  });
});
